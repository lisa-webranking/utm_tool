terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ---------------------------------------------------------------------------
# APIs
# ---------------------------------------------------------------------------
resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
  ])
  service            = each.key
  disable_on_destroy = false
}

# ---------------------------------------------------------------------------
# Artifact Registry (container images)
# ---------------------------------------------------------------------------
resource "google_artifact_registry_repository" "repo" {
  location      = var.region
  repository_id = var.service_name
  format        = "DOCKER"
  depends_on    = [google_project_service.apis]
}

# ---------------------------------------------------------------------------
# Cloud SQL — PostgreSQL 15
# ---------------------------------------------------------------------------
resource "random_password" "db_password" {
  length  = 24
  special = false
}

resource "google_sql_database_instance" "main" {
  name             = "${var.service_name}-db"
  region           = var.region
  database_version = "POSTGRES_15"

  settings {
    tier              = var.db_tier
    availability_type = "ZONAL"
    disk_size         = 10
    disk_autoresize   = true

    ip_configuration {
      # Cloud Run connects via Cloud SQL Auth Proxy (Unix socket),
      # so we only need a minimal IP config. Enable public IP for
      # initial schema migration via gcloud sql connect.
      ipv4_enabled    = true
      require_ssl     = true
      authorized_networks {}
    }

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
    }
  }

  deletion_protection = true
  depends_on          = [google_project_service.apis]
}

resource "google_sql_database" "app" {
  name     = "utm_tool"
  instance = google_sql_database_instance.main.name
}

resource "google_sql_user" "app" {
  name     = "utm_app"
  instance = google_sql_database_instance.main.name
  password = random_password.db_password.result
}

# ---------------------------------------------------------------------------
# Secret Manager
# ---------------------------------------------------------------------------
resource "google_secret_manager_secret" "db_url" {
  secret_id = "${var.service_name}-database-url"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "db_url" {
  secret      = google_secret_manager_secret.db_url.id
  secret_data = "postgresql://${google_sql_user.app.name}:${random_password.db_password.result}@/${google_sql_database.app.name}?host=/cloudsql/${google_sql_database_instance.main.connection_name}"
}

resource "google_secret_manager_secret" "client_link_secret" {
  secret_id = "${var.service_name}-client-link-secret"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

# OAuth client_secrets.json — created manually, add version via CLI:
# gcloud secrets versions add utm-tool-oauth-client --data-file=client_secrets.json
resource "google_secret_manager_secret" "oauth_client" {
  secret_id = "${var.service_name}-oauth-client"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------------------
# Service Account for Cloud Run
# ---------------------------------------------------------------------------
resource "google_service_account" "runner" {
  account_id   = "${var.service_name}-runner"
  display_name = "Cloud Run service account for ${var.service_name}"
}

# Allow Cloud Run SA to access secrets
resource "google_secret_manager_secret_iam_member" "runner_db_url" {
  secret_id = google_secret_manager_secret.db_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runner.email}"
}

resource "google_secret_manager_secret_iam_member" "runner_client_link" {
  secret_id = google_secret_manager_secret.client_link_secret.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runner.email}"
}

resource "google_secret_manager_secret_iam_member" "runner_oauth" {
  secret_id = google_secret_manager_secret.oauth_client.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runner.email}"
}

# Allow Cloud Run SA to connect to Cloud SQL
resource "google_project_iam_member" "runner_sql" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.runner.email}"
}

# ---------------------------------------------------------------------------
# Cloud Run
# ---------------------------------------------------------------------------
resource "google_cloud_run_v2_service" "app" {
  name     = var.service_name
  location = var.region

  template {
    service_account = google_service_account.runner.email

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.repo.repository_id}/${var.service_name}:latest"

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }

      startup_probe {
        http_get {
          path = "/_stcore/health"
        }
        initial_delay_seconds = 10
        period_seconds        = 5
        failure_threshold     = 6
      }

      liveness_probe {
        http_get {
          path = "/_stcore/health"
        }
        period_seconds = 30
      }

      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.db_url.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "CLIENT_LINK_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.client_link_secret.secret_id
            version = "latest"
          }
        }
      }

      env {
        name  = "OAUTH_REDIRECT_URI"
        value = var.custom_domain != "" ? "https://${var.custom_domain}/" : ""
        # When empty, app.py falls back to the Cloud Run URL or localhost
      }

      volume_mounts {
        name       = "oauth-client"
        mount_path = "/secrets/oauth"
      }
    }

    volumes {
      name = "oauth-client"
      secret {
        secret = google_secret_manager_secret.oauth_client.secret_id
        items {
          version = "latest"
          path    = "client_secrets.json"
        }
      }
    }

    annotations = {
      "run.googleapis.com/cloudsql-instances" = google_sql_database_instance.main.connection_name
    }

    session_affinity = true

    timeout = "300s"
  }

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_version.db_url,
  ]
}

# Allow unauthenticated access (public web app)
resource "google_cloud_run_v2_service_iam_member" "public" {
  name     = google_cloud_run_v2_service.app.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------
output "service_url" {
  value = google_cloud_run_v2_service.app.uri
}

output "cloud_sql_connection_name" {
  value = google_sql_database_instance.main.connection_name
}

output "artifact_registry" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.repo.repository_id}"
}
