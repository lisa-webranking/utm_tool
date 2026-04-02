# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the App

```bash
pip install -r requirements.txt
streamlit run app.py
```

For Codespaces/devcontainer, the app auto-starts on port 8501 with CORS and XSRF disabled.

There are no tests or linting configured in this project.

## Prerequisites

- `client_secrets.json` from Google Cloud Console (OAuth 2.0 Web Client ID) in the project root
- A Gemini API key (entered per-user in the UI, persisted to `api_keys.json`)

## Architecture

Streamlit application for UTM link governance with GA4 integration and a Gemini-powered AI assistant. The UI is in Italian.

### Entry Point (`app.py` — ~200KB, monolithic)
- Google OAuth 2.0 login flow (port 8080) with PKCE; scopes for Analytics + user profile; server-side cache for `code_verifier` to survive Streamlit websocket restarts
- Two main tabs: **UTM Generator** (builder with real-time validation) and **UTM Checker** (URL parameter analysis)
- GA4 account/property selection and live traffic source fetching
- `GUIDE_TABLE_DATA` — channel mapping table that drives source/medium recommendations
- Uses `st.session_state` extensively for auth credentials, GA4 accounts, chat messages, and API keys
- Extensive inline CSS (~300 lines) for custom "Loveable" design system using CSS variables

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

### GA4 Tools (`ga4_mcp_tools.py`)
- Wraps Google Analytics Admin and Data APIs behind simple Python functions
- Functions: `get_account_summaries`, `get_property_details`, `run_report`, `run_realtime_report`, `list_google_ads_links`
- All functions accept `creds` (Google OAuth credentials) as a parameter
- Property IDs use the format `properties/123456`

### Google API Helpers (`googleapi.py`)
- `get_user_email(creds)`: fetches authenticated user's email via OAuth2 userinfo API
- `get_persistent_api_key(email)` / `save_persistent_api_key(email, key)`: stores per-user Gemini API keys in `api_keys.json`

### Skill Definition Files
- `skill_utm_generation.md` — defines the chatbot's UTM generation skill (trigger conditions, required inputs, naming conventions)
- `skill MCP Checker.md` — defines GA4 post-live check logic (session verification, channel attribution validation, error/warning states)

## Key Conventions

- UTM values are normalized to lowercase, hyphens/underscores only, via `python-slugify` (`normalize_token` in app.py) and `_sanitize_utm_value` in chatbot_ui.py
- Campaign naming pattern: `Country_Type_Name_Date_CTA` (date format YYYYMMDD in builder, DD-MM-YYYY in chatbot)
- URLs are normalized to `https://www.` prefix by the chatbot
- Client config IDs are normalized with `normalize_client_id()` before filesystem operations
- Sensitive files (`token.json`, `client_secrets.json`, `api_keys.json`) are in `.gitignore`
- Source encoding is `latin-1` (declared in app.py header) due to Italian characters in inline strings
