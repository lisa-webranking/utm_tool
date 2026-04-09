#!/usr/bin/env bash
#
# UTM Governance Tool — GCP infrastructure setup (Firestore edition)
#
# Provisions: Firestore, Secret Manager, Artifact Registry, Service Account,
#             IAM bindings, and deploys to Cloud Run.
#
# Prerequisites:
#   - gcloud CLI authenticated (gcloud auth login)
#   - A GCP project with billing enabled
#   - Docker running locally
#   - client_secrets.json from Google Cloud Console (OAuth 2.0 Web Client ID)
#     OR secrets configured in .streamlit/secrets.toml
#   - Optional for non-interactive bootstrap: GEMINI_API_KEY environment variable
#
# Usage:
#   ./infra/setup.sh                          # Interactive — prompts for project ID
#   ./infra/setup.sh --project my-project-id  # Non-interactive
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SERVICE_NAME="utm-tool"
REGION="europe-west8"       # Milan
MIN_INSTANCES=0             # 0 = scale to zero (free when idle)
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
GEMINI_SECRET_ID="${GEMINI_SECRET_ID:-${PROJECT_ID}_gemini_api-key}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! git -C "${REPO_ROOT}" diff --quiet --ignore-submodules -- || \
   ! git -C "${REPO_ROOT}" diff --cached --quiet --ignore-submodules --; then
    echo "ERROR: Refusing to deploy from a dirty worktree."
    echo "Commit or stash tracked changes first so the built image matches a real commit."
    exit 1
fi

SOURCE_SHA="$(git -C "${REPO_ROOT}" rev-parse HEAD)"
SOURCE_SHA_SHORT="$(git -C "${REPO_ROOT}" rev-parse --short=12 HEAD)"
BUILD_DIR="$(mktemp -d)"

cleanup() {
    rm -rf "${BUILD_DIR}"
}

trap cleanup EXIT

echo ""
echo "=== UTM Tool — GCP Setup (Firestore) ==="
echo "  Project:    ${PROJECT_ID}"
echo "  Region:     ${REGION}"
echo "  Service:    ${SERVICE_NAME}"
echo "  Registry:   ${IMAGE}"
echo "  Source SHA: ${SOURCE_SHA_SHORT}"
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
echo "--- 1/7 Enabling APIs ---"
gcloud services enable \
    run.googleapis.com \
    firestore.googleapis.com \
    secretmanager.googleapis.com \
    artifactregistry.googleapis.com \
    --quiet

# ---------------------------------------------------------------------------
# 2. Artifact Registry
# ---------------------------------------------------------------------------
echo ""
echo "--- 2/7 Artifact Registry ---"
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
# 3. Firestore (Native mode)
# ---------------------------------------------------------------------------
echo ""
echo "--- 3/7 Firestore ---"
EXISTING_DB=$(gcloud firestore databases list --format="value(name)" 2>/dev/null || echo "")
if [[ -n "$EXISTING_DB" ]]; then
    echo "  Firestore database already exists."
else
    gcloud firestore databases create \
        --location="${REGION}" \
        --type=firestore-native \
        --quiet
    echo "  Created (Native mode, ${REGION})."
fi

# ---------------------------------------------------------------------------
# 4. Secret Manager
# ---------------------------------------------------------------------------
echo ""
echo "--- 4/7 Secret Manager ---"

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

ensure_gemini_secret() {
    if gcloud secrets describe "${GEMINI_SECRET_ID}" --format="value(name)" 2>/dev/null; then
        echo "  Reusing: ${GEMINI_SECRET_ID}"
        return
    fi

    local gemini_api_key="${GEMINI_API_KEY:-}"
    if [[ -z "${gemini_api_key}" && "${SKIP_CONFIRM}" != true ]]; then
        echo "  Shared Gemini secret not found."
        echo "  Enter the Gemini API key to create ${GEMINI_SECRET_ID}:"
        read -rs gemini_api_key
        echo ""
    fi

    if [[ -z "${gemini_api_key}" ]]; then
        echo "  ERROR: Missing Gemini secret ${GEMINI_SECRET_ID}."
        echo "  Create it in Secret Manager or provide GEMINI_API_KEY for non-interactive bootstrap."
        exit 1
    fi

    create_or_update_secret "${GEMINI_SECRET_ID}" "${gemini_api_key}"
}

# CLIENT_LINK_SECRET — create once, keep stable across redeploys
if gcloud secrets describe "${SERVICE_NAME}-client-link-secret" --format="value(name)" 2>/dev/null; then
    echo "  Reusing: ${SERVICE_NAME}-client-link-secret"
else
    LINK_SECRET=$(openssl rand -base64 32)
    create_or_update_secret "${SERVICE_NAME}-client-link-secret" "${LINK_SECRET}"
fi

# OAuth client_secrets.json
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

ensure_gemini_secret

# ---------------------------------------------------------------------------
# 5. Service Account + IAM
# ---------------------------------------------------------------------------
echo ""
echo "--- 5/7 Service Account & IAM ---"

if gcloud iam service-accounts describe "${SA_EMAIL}" --format="value(email)" 2>/dev/null; then
    echo "  Service account already exists."
else
    gcloud iam service-accounts create "${SA_NAME}" \
        --display-name="Cloud Run runner for ${SERVICE_NAME}" --quiet
    echo "  Created: ${SA_EMAIL}"
fi

# Secret access
for secret in "${SERVICE_NAME}-client-link-secret" "${SERVICE_NAME}-oauth-client" "${GEMINI_SECRET_ID}"; do
    gcloud secrets add-iam-policy-binding "${secret}" \
        --member="serviceAccount:${SA_EMAIL}" \
        --role="roles/secretmanager.secretAccessor" --quiet 2>/dev/null
done
echo "  Secret access granted."

# Firestore access
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/datastore.user" --quiet 2>/dev/null
echo "  Firestore access granted."

# ---------------------------------------------------------------------------
# 6. Build & push container
# ---------------------------------------------------------------------------
echo ""
echo "--- 6/7 Build & Push (${SOURCE_SHA_SHORT}) ---"
gcloud auth configure-docker "${REGISTRY}" --quiet

git -C "${REPO_ROOT}" archive HEAD | tar -x -C "${BUILD_DIR}"

docker build -t "${IMAGE}:${SOURCE_SHA}" "${BUILD_DIR}"
docker push "${IMAGE}:${SOURCE_SHA}"
IMAGE_DIGEST="$(docker inspect --format='{{index .RepoDigests 0}}' "${IMAGE}:${SOURCE_SHA}")"
echo "  Pushed: ${IMAGE}:${SOURCE_SHA_SHORT}"
echo "  Digest: ${IMAGE_DIGEST}"

# ---------------------------------------------------------------------------
# 7. Deploy to Cloud Run
# ---------------------------------------------------------------------------
echo ""
echo "--- 7/7 Deploy to Cloud Run ---"

gcloud run deploy "${SERVICE_NAME}" \
    --image="${IMAGE_DIGEST}" \
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
    --set-env-vars="USE_FIRESTORE=1" \
    --set-secrets="CLIENT_LINK_SECRET=${SERVICE_NAME}-client-link-secret:latest,GEMINI_API_KEY=${GEMINI_SECRET_ID}:latest" \
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
echo "  URL:        ${SERVICE_URL}"
echo "  Firestore:  Native mode (${REGION})"
echo "  Registry:   ${IMAGE_DIGEST}"
echo "  Source SHA: ${SOURCE_SHA}"
echo ""
echo "  Next steps:"
echo "    1. Add these to Google Cloud Console > Credentials:"
echo "       Authorized JavaScript origins: ${SERVICE_URL}"
echo "       Authorized redirect URIs:      ${SERVICE_URL}/"
echo "    2. Set OAUTH_REDIRECT_URI:"
echo "       gcloud run services update ${SERVICE_NAME} --region=${REGION} \\"
echo "         --set-env-vars=OAUTH_REDIRECT_URI=${SERVICE_URL}/"
echo "============================================"
