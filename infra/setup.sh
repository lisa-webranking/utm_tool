#!/usr/bin/env bash
#
# UTM Governance Tool — GCP infrastructure setup
#
# Provisions: Cloud SQL, Secret Manager, Artifact Registry, Service Account,
#             IAM bindings, and deploys to Cloud Run.
#
# Prerequisites:
#   - gcloud CLI authenticated (gcloud auth login)
#   - A GCP project with billing enabled
#   - client_secrets.json from Google Cloud Console (OAuth 2.0 Web Client ID)
#
# Usage:
#   ./infra/setup.sh                          # Interactive — prompts for project ID
#   ./infra/setup.sh --project my-project-id  # Non-interactive
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration (edit these or pass via flags)
# ---------------------------------------------------------------------------
SERVICE_NAME="utm-tool"
REGION="europe-west8"       # Milan — change to your preferred region
DB_TIER="db-f1-micro"       # Smallest tier, ~$9/month
DB_NAME="utm_tool"
DB_USER="utm_app"
MIN_INSTANCES=1             # 1 = no cold start (~$15/month idle)
MAX_INSTANCES=3

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
PROJECT_ID=""
SKIP_CONFIRM=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --project)  PROJECT_ID="$2"; shift 2 ;;
        --region)   REGION="$2"; shift 2 ;;
        --yes|-y)   SKIP_CONFIRM=true; shift ;;
        *)          echo "Unknown flag: $1"; exit 1 ;;
    esac
done

if [[ -z "$PROJECT_ID" ]]; then
    echo "Enter your GCP project ID:"
    read -r PROJECT_ID
fi

REGISTRY="${REGION}-docker.pkg.dev"
IMAGE="${REGISTRY}/${PROJECT_ID}/${SERVICE_NAME}/${SERVICE_NAME}"
SA_NAME="${SERVICE_NAME}-runner"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
DB_INSTANCE="${SERVICE_NAME}-db"

echo ""
echo "=== UTM Tool — GCP Setup ==="
echo "  Project:    ${PROJECT_ID}"
echo "  Region:     ${REGION}"
echo "  Service:    ${SERVICE_NAME}"
echo "  DB:         ${DB_INSTANCE} (${DB_TIER})"
echo "  Registry:   ${IMAGE}"
echo ""

if [[ "$SKIP_CONFIRM" != true ]]; then
    read -rp "Continue? (y/N) " confirm
    [[ "$confirm" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }
fi

gcloud config set project "${PROJECT_ID}"

# ---------------------------------------------------------------------------
# 1. Enable APIs
# ---------------------------------------------------------------------------
echo ""
echo "--- 1/8 Enabling APIs ---"
gcloud services enable \
    run.googleapis.com \
    sqladmin.googleapis.com \
    secretmanager.googleapis.com \
    artifactregistry.googleapis.com \
    --quiet

# ---------------------------------------------------------------------------
# 2. Artifact Registry
# ---------------------------------------------------------------------------
echo ""
echo "--- 2/8 Artifact Registry ---"
if gcloud artifacts repositories describe "${SERVICE_NAME}" \
    --location="${REGION}" --format="value(name)" 2>/dev/null; then
    echo "  Repository already exists."
else
    gcloud artifacts repositories create "${SERVICE_NAME}" \
        --repository-format=docker \
        --location="${REGION}" \
        --quiet
    echo "  Created."
fi

# ---------------------------------------------------------------------------
# 3. Cloud SQL (PostgreSQL 15)
# ---------------------------------------------------------------------------
echo ""
echo "--- 3/8 Cloud SQL ---"
DB_PASSWORD=$(openssl rand -base64 18 | tr -dc 'a-zA-Z0-9' | head -c 24)

if gcloud sql instances describe "${DB_INSTANCE}" --format="value(name)" 2>/dev/null; then
    echo "  Instance already exists."
    CONNECTION_NAME=$(gcloud sql instances describe "${DB_INSTANCE}" --format="value(connectionName)")
else
    echo "  Creating instance (this takes 3-5 minutes)..."
    gcloud sql instances create "${DB_INSTANCE}" \
        --database-version=POSTGRES_15 \
        --tier="${DB_TIER}" \
        --region="${REGION}" \
        --availability-type=ZONAL \
        --storage-size=10GB \
        --storage-auto-increase \
        --backup \
        --enable-point-in-time-recovery \
        --quiet
    CONNECTION_NAME=$(gcloud sql instances describe "${DB_INSTANCE}" --format="value(connectionName)")
    echo "  Created: ${CONNECTION_NAME}"
fi

# Create database and user (idempotent)
gcloud sql databases create "${DB_NAME}" \
    --instance="${DB_INSTANCE}" 2>/dev/null || echo "  Database already exists."

gcloud sql users create "${DB_USER}" \
    --instance="${DB_INSTANCE}" \
    --password="${DB_PASSWORD}" 2>/dev/null || \
    gcloud sql users set-password "${DB_USER}" \
        --instance="${DB_INSTANCE}" \
        --password="${DB_PASSWORD}"

echo "  User ${DB_USER} configured."

# Build DATABASE_URL for Cloud SQL Auth Proxy (Unix socket)
CONNECTION_NAME=$(gcloud sql instances describe "${DB_INSTANCE}" --format="value(connectionName)")
DATABASE_URL="postgresql://${DB_USER}:${DB_PASSWORD}@/${DB_NAME}?host=/cloudsql/${CONNECTION_NAME}"

# ---------------------------------------------------------------------------
# 4. Apply schema
# ---------------------------------------------------------------------------
echo ""
echo "--- 4/8 Applying database schema ---"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${SCRIPT_DIR}/schema.sql" ]]; then
    gcloud sql connect "${DB_INSTANCE}" --database="${DB_NAME}" --quiet < "${SCRIPT_DIR}/schema.sql"
    echo "  Schema applied."
else
    echo "  WARNING: schema.sql not found in ${SCRIPT_DIR}. Apply manually."
fi

# ---------------------------------------------------------------------------
# 5. Secret Manager
# ---------------------------------------------------------------------------
echo ""
echo "--- 5/8 Secret Manager ---"

create_or_update_secret() {
    local secret_id="$1"
    local secret_data="$2"

    if gcloud secrets describe "${secret_id}" --format="value(name)" 2>/dev/null; then
        echo "${secret_data}" | gcloud secrets versions add "${secret_id}" --data-file=- --quiet
        echo "  Updated: ${secret_id}"
    else
        echo "${secret_data}" | gcloud secrets create "${secret_id}" --data-file=- \
            --replication-policy=automatic --quiet
        echo "  Created: ${secret_id}"
    fi
}

create_or_update_secret "${SERVICE_NAME}-database-url" "${DATABASE_URL}"

# CLIENT_LINK_SECRET — generate if not already set
LINK_SECRET=$(openssl rand -base64 32)
create_or_update_secret "${SERVICE_NAME}-client-link-secret" "${LINK_SECRET}"

# OAuth client_secrets.json — check if local file exists
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
if [[ -f "${REPO_ROOT}/client_secrets.json" ]]; then
    if gcloud secrets describe "${SERVICE_NAME}-oauth-client" --format="value(name)" 2>/dev/null; then
        gcloud secrets versions add "${SERVICE_NAME}-oauth-client" \
            --data-file="${REPO_ROOT}/client_secrets.json" --quiet
    else
        gcloud secrets create "${SERVICE_NAME}-oauth-client" \
            --data-file="${REPO_ROOT}/client_secrets.json" \
            --replication-policy=automatic --quiet
    fi
    echo "  Uploaded: client_secrets.json"
else
    echo "  WARNING: client_secrets.json not found. Upload manually:"
    echo "    gcloud secrets create ${SERVICE_NAME}-oauth-client \\"
    echo "      --data-file=client_secrets.json --replication-policy=automatic"
fi

# ---------------------------------------------------------------------------
# 6. Service Account + IAM
# ---------------------------------------------------------------------------
echo ""
echo "--- 6/8 Service Account & IAM ---"

if gcloud iam service-accounts describe "${SA_EMAIL}" --format="value(email)" 2>/dev/null; then
    echo "  Service account already exists."
else
    gcloud iam service-accounts create "${SA_NAME}" \
        --display-name="Cloud Run runner for ${SERVICE_NAME}" --quiet
    echo "  Created: ${SA_EMAIL}"
fi

# Secret access
for secret in "${SERVICE_NAME}-database-url" "${SERVICE_NAME}-client-link-secret" "${SERVICE_NAME}-oauth-client"; do
    gcloud secrets add-iam-policy-binding "${secret}" \
        --member="serviceAccount:${SA_EMAIL}" \
        --role="roles/secretmanager.secretAccessor" --quiet 2>/dev/null
done
echo "  Secret access granted."

# Cloud SQL client
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/cloudsql.client" --quiet 2>/dev/null
echo "  Cloud SQL access granted."

# ---------------------------------------------------------------------------
# 7. Build & push container
# ---------------------------------------------------------------------------
echo ""
echo "--- 7/8 Build & Push ---"
gcloud auth configure-docker "${REGISTRY}" --quiet

docker build -t "${IMAGE}:latest" "${REPO_ROOT}"
docker push "${IMAGE}:latest"
echo "  Pushed: ${IMAGE}:latest"

# ---------------------------------------------------------------------------
# 8. Deploy to Cloud Run
# ---------------------------------------------------------------------------
echo ""
echo "--- 8/8 Deploy to Cloud Run ---"

gcloud run deploy "${SERVICE_NAME}" \
    --image="${IMAGE}:latest" \
    --region="${REGION}" \
    --platform=managed \
    --service-account="${SA_EMAIL}" \
    --allow-unauthenticated \
    --session-affinity \
    --min-instances="${MIN_INSTANCES}" \
    --max-instances="${MAX_INSTANCES}" \
    --memory=1Gi \
    --cpu=1 \
    --timeout=300 \
    --set-secrets="DATABASE_URL=${SERVICE_NAME}-database-url:latest,CLIENT_LINK_SECRET=${SERVICE_NAME}-client-link-secret:latest" \
    --add-cloudsql-instances="${CONNECTION_NAME}" \
    --update-secrets="/secrets/oauth/client_secrets.json=${SERVICE_NAME}-oauth-client:latest" \
    --quiet

SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
    --region="${REGION}" --format="value(status.url)")

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo "============================================"
echo "  Deploy complete!"
echo ""
echo "  URL:            ${SERVICE_URL}"
echo "  Cloud SQL:      ${CONNECTION_NAME}"
echo "  Registry:       ${IMAGE}"
echo ""
echo "  Next steps:"
echo "    1. Add ${SERVICE_URL}/ as authorized redirect URI"
echo "       in Google Cloud Console > APIs & Services > Credentials"
echo "    2. Set OAUTH_REDIRECT_URI:"
echo "       gcloud run services update ${SERVICE_NAME} --region=${REGION} \\"
echo "         --set-env-vars=OAUTH_REDIRECT_URI=${SERVICE_URL}/"
echo "============================================"
