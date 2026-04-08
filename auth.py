"""
OAuth 2.0 authentication and credential management.

Extracted from app.py to isolate auth logic from UI rendering.
All functions that touch st.session_state are wrappers in app.py —
this module contains the pure credential operations.
"""
import json
import logging
import os
from pathlib import Path
from typing import Optional

import streamlit as st
from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/analytics.edit",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]


def build_oauth_flow(
    secrets_path: Path,
    redirect_uri_override: str = "",
    config_value_func=None,
):
    """Configure and return a Google OAuth 2.0 Flow object.

    Args:
        secrets_path: Path to client_secrets.json
        redirect_uri_override: Explicit redirect URI (from env var)
        config_value_func: Callable to read config values (e.g. from st.secrets)
    """
    from google_auth_oauthlib.flow import Flow

    client_config = None

    # Cloud Run mounts secrets to /secrets/oauth/client_secrets.json
    cloud_run_path = Path("/secrets/oauth/client_secrets.json")

    # Check st.secrets safely (raises if secrets.toml doesn't exist)
    def _has_secret(key: str) -> bool:
        try:
            return key in st.secrets
        except Exception:
            return False

    if secrets_path.exists():
        with open(secrets_path, "r") as f:
            client_config = json.load(f)
    elif cloud_run_path.exists():
        with open(cloud_run_path, "r") as f:
            client_config = json.load(f)
    elif _has_secret("google_oauth"):
        client_config = {"web": dict(st.secrets["google_oauth"])}
    else:
        return None

    flow = Flow.from_client_config(client_config, scopes=SCOPES)

    # redirect_uri: explicit override > st.secrets > localhost fallback
    redirect_uri = redirect_uri_override.strip() if redirect_uri_override else ""
    if not redirect_uri and config_value_func:
        redirect_uri = config_value_func("redirect_uri")
    if not redirect_uri:
        redirect_uri = "http://localhost:8501/"

    flow.redirect_uri = redirect_uri
    return flow


def save_credentials(creds: Credentials, cred_store, legacy_path: Path) -> None:
    """Do not persist OAuth credentials outside the active browser session.

    The app now treats Google auth as strictly session-scoped. Keeping refresh
    tokens in server-side storage made session isolation ambiguous and could
    leak one operator's authenticated state into a later visit. The legacy
    path is kept only so logout can remove stale tokens created by older
    versions.
    """
    logger.debug("Skipping credential persistence: auth is session-scoped only")


def load_credentials(cred_store, legacy_path: Path) -> Optional[Credentials]:
    """Never restore credentials from server-side persistence.

    A fresh browser session must always start anonymous and complete its own
    OAuth flow. This keeps authentication ownership aligned with the current
    visitor instead of any previously persisted token.
    """
    return None


def logout(cred_store, legacy_path: Path) -> None:
    """Clear session and persisted credentials."""
    email = st.session_state.get("user_email", "")
    for key in ("credentials", "user_email", "gemini_api_key", "google_credentials"):
        st.session_state.pop(key, None)
    st.session_state.pop("ga4_accounts", None)
    st.session_state.pop("ga4_cache_user_email", None)
    if email:
        cred_store.delete_token(email)
    try:
        if legacy_path.exists():
            legacy_path.unlink()
    except Exception:
        pass
