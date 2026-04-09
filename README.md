# Universal UTM Governance

A powerful Streamlit application to generate, manage, and validate UTM links with Google Analytics 4 integration and a Gemini-powered AI Assistant.

## Features
- **UTM Generator**: Create standardized links with predefined channel mappings.
- **UTM Checker**: Validate existing links for HTTPS, length, and mandatory parameters.
- **AI Assistant**: Gemini-powered chat (Bot-style UI) using a shared server-side Gemini key to analyze GA4 data with MCP tools.
- **GA4 Integration**: Fetch real traffic sources and property data directly from your account.
- **Session-scoped auth**: each person logs in with their own Google account, shared links carry client context only.

## Local setup
1. Clone the repository.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Provide Google OAuth client credentials locally:
   - preferred: `client_secrets.json` in the project root
   - fallback: `.streamlit/secrets.toml` with `[google_oauth]`
4. Provide the shared Gemini key server-side:
   ```bash
   export GEMINI_API_KEY="your-key"
   ```
5. Run the app:
   ```bash
   streamlit run app.py
   ```

## Deployment

### Default production path

Production deploys are handled by `.github/workflows/deploy.yml`.

- Trigger: push to `main` or manual workflow dispatch
- Build: Docker image tagged with `GITHUB_SHA`
- Release: Cloud Run deploy by immutable image digest
- Runtime secret mapping: `GEMINI_API_KEY` from Secret Manager

Required GitHub repository configuration:

- Variable: `GCP_PROJECT_ID`
- Auth, choose one:
  - Secret: `GCP_SA_KEY`
  - Variables: `WIF_PROVIDER` and `WIF_SERVICE_ACCOUNT`
- Optional variable: `GEMINI_SECRET_ID`
  - if omitted, the workflow derives `${PROJECT_ID}_gemini_api-key`

### Manual bootstrap

For a fresh project, use `infra/setup.sh`:

```bash
GEMINI_API_KEY="your-key" ./infra/setup.sh --project your-gcp-project-id
```

Behavior:

- creates Artifact Registry, Firestore, Cloud Run service account, and required secrets
- reuses `CLIENT_LINK_SECRET` across redeploys
- creates the Gemini secret if missing from `GEMINI_API_KEY`
- if `GEMINI_API_KEY` is not set and the shell is interactive, prompts for it securely

## Verification

Regression checks currently in repo:

```bash
python -m unittest \
  tests/test_auth_session_isolation.py \
  tests/test_gemini_config.py \
  tests/test_gemini_deploy_config.py
```

## Security
Ensure `token.json`, `client_secrets.json`, and `.streamlit/secrets.toml` are **never** committed to Git. The Gemini key is shared server-side and should never be entered in the UI or committed to the repository.
