# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
Keep this file aligned with auth, runtime config, and deploy behavior. Other coding agents rely on it as operational context.

## Running the App

```bash
pip install -r requirements.txt
streamlit run app.py
```

For Codespaces/devcontainer, the app auto-starts on port 8501 with CORS and XSRF disabled.

There is a small `unittest` regression suite. Run:

```bash
python -m unittest \
  tests/test_auth_session_isolation.py \
  tests/test_account_menu_ui.py \
  tests/test_gemini_config.py \
  tests/test_gemini_deploy_config.py
```

No linting is configured in this project.

## Prerequisites

- Local OAuth config:
  - preferred: `client_secrets.json` from Google Cloud Console (OAuth 2.0 Web Client ID) in the project root
  - fallback: `.streamlit/secrets.toml` with `[google_oauth]`
- Shared Gemini runtime config:
  - `GEMINI_API_KEY` via environment variable, `st.secrets`, or Cloud Run Secret Manager mapping
  - end users no longer paste their own Gemini key in the UI

## Deployment

Default production path: `.github/workflows/deploy.yml`.

- Trigger: push to `main` or `workflow_dispatch`
- Auth to GCP:
  - preferred fallback currently supported: GitHub secret `GCP_SA_KEY`
  - alternative: `WIF_PROVIDER` + `WIF_SERVICE_ACCOUNT`
- Required repo variable: `GCP_PROJECT_ID`
- Optional repo variable: `GEMINI_SECRET_ID`
  - if omitted, workflow derives `${PROJECT_ID}_gemini_api-key`
- Deploy target: Cloud Run, by immutable image digest
- Runtime secret mapping:
  - `GEMINI_API_KEY` -> Secret Manager
  - `/secrets/oauth/client_secrets.json` -> OAuth client secret mount

Manual/fresh-project bootstrap: `infra/setup.sh`.

- `GEMINI_API_KEY="..." ./infra/setup.sh --project <gcp-project-id>` creates missing Gemini secret during bootstrap
- if `GEMINI_API_KEY` is missing and the shell is interactive, the script prompts securely
- the script reuses `CLIENT_LINK_SECRET` across redeploys
- the script refuses deploys from a dirty tracked worktree

## Architecture

Streamlit application for UTM link governance with GA4 integration and a Gemini-powered AI assistant. The UI is in Italian.

### Entry Point (`app.py` — ~200KB, monolithic)
- Google OAuth 2.0 login flow with PKCE and same-browser auth persistence; credentials are restored only when the browser presents the first-party session cookie and the matching server-side token exists
- Two main tabs: **UTM Generator** (builder with real-time validation) and **UTM Checker** (URL parameter analysis)
- GA4 account/property selection and live traffic source fetching
- `GUIDE_TABLE_DATA` — channel mapping table that drives source/medium recommendations
- Uses `st.session_state` extensively for auth credentials, GA4 accounts, chat messages, and shared Gemini key state
- Extensive inline CSS (~300 lines) for custom "Loveable" design system using CSS variables
- Account controls expose logout only; there is no user-facing settings modal anymore

### Client Config System (`client_configs/`)
- Per-client JSON files (e.g., `chicco_2023.json`, `ovs.json`) containing UTM rules imported from Excel
- Each config has: `client_id`, `version`, `rules_rows` (parsed from Excel sheets), `source_file_sha256` for integrity
- `load_client_config()` / `save_client_config()` in app.py manage CRUD; configs are selected in the sidebar
- `build_client_rules_text_for_chatbot()` converts a client config into a text block injected into the Gemini system prompt, so the chatbot enforces client-specific naming rules
- Helper extractors: `extract_client_rule_values`, `extract_client_field_examples`, `extract_client_medium_source_map`, `extract_client_campaign_rule_notes`

### Chatbot UI (`chatbot_ui.py`)
- Renders the "WR Assistant" inline chat widget in the right column of the Generator tab
- URL normalization, UTM value sanitization, and LLM output cleaning utilities (`clean_bot_response`, `_dedupe_repetitions`, `_normalize_destination_url`)
- `get_gemini_response_safe()` tries multiple Gemini models in fallback order (2.0-flash → 1.5-flash → 1.5-pro → 1.0-pro)
- Registers GA4 tool functions (list properties, run reports, guess property from URL) for Gemini's automatic function calling
- System instruction defines an 8-step conversational flow for UTM link creation
- Expects `st.session_state["gemini_api_key"]` to be injected from server-side config before chat execution

### GA4 Tools (`ga4_mcp_tools.py`)
- Wraps Google Analytics Admin and Data APIs behind simple Python functions
- Functions: `get_account_summaries`, `get_property_details`, `run_report`, `run_realtime_report`, `list_google_ads_links`
- All functions accept `creds` (Google OAuth credentials) as a parameter
- Property IDs use the format `properties/123456`

### Google API Helpers (`googleapi.py`)
- `get_user_email(creds)`: fetches authenticated user's email via OAuth2 userinfo API
- `get_shared_gemini_api_key(config_value_func=None)`: resolves the shared Gemini key from environment or config
- `get_persistent_api_key(email)` / `save_persistent_api_key(email, key)`: legacy helpers still present in the module, but runtime code should not use them

### Skill Definition Files
- `skill_utm_generation.md` — defines the chatbot's UTM generation skill (trigger conditions, required inputs, naming conventions)
- `skill MCP Checker.md` — defines GA4 post-live check logic (session verification, channel attribution validation, error/warning states)

## Key Conventions

- UTM values are normalized to lowercase, hyphens/underscores only, via `python-slugify` (`normalize_token` in app.py) and `_sanitize_utm_value` in chatbot_ui.py
- Campaign naming pattern: `Country_Type_Name_Date_CTA` (date format YYYYMMDD in builder, DD-MM-YYYY in chatbot)
- URLs are normalized to `https://www.` prefix by the chatbot
- Client config IDs are normalized with `normalize_client_id()` before filesystem operations
- OAuth persistence is scoped to the same browser through a first-party `wr_browser_session` cookie plus a matching server-side credential record
- Shared Gemini access is system-managed through `GEMINI_API_KEY`, not user-supplied through the UI
- Sensitive files (`token.json`, `client_secrets.json`, `.streamlit/secrets.toml`) are in `.gitignore`
- Source encoding is `latin-1` (declared in app.py header) due to Italian characters in inline strings
