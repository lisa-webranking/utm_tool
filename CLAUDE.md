# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the App

```bash
pip install -r requirements.txt
streamlit run app.py
```

There are no tests or linting configured in this project.

## Architecture

This is a **Streamlit** application for UTM link governance with GA4 integration and a Gemini-powered AI assistant. The UI is in Italian.

### Entry Point & Main App (`app.py`)
- Handles Google OAuth 2.0 login flow (port 8080) with scopes for Analytics + user profile
- Contains two main tabs: **UTM Generator** (builder with real-time validation) and **UTM Checker** (URL parameter analysis)
- Manages GA4 account/property selection and fetches live traffic sources
- Uses `st.session_state` extensively for auth credentials, GA4 accounts, chat messages, and API keys
- Defines the `GUIDE_TABLE_DATA` channel mapping table that drives source/medium recommendations

### Chatbot UI (`chatbot_ui.py`)
- Renders the "WR Assistant" inline chat widget in the right column of the Generator tab
- Contains URL normalization, UTM value sanitization, and LLM output cleaning utilities (`clean_bot_response`, `_dedupe_repetitions`, `_normalize_destination_url`)
- `get_gemini_response_safe()` tries multiple Gemini models in fallback order (2.0-flash -> 1.5-flash -> 1.5-pro -> 1.0-pro)
- Registers GA4 tool functions (list properties, run reports, guess property from URL) for Gemini's automatic function calling
- The system instruction defines an 8-step conversational flow for UTM link creation

### GA4 Tools (`ga4_mcp_tools.py`)
- Wraps Google Analytics Admin and Data APIs behind simple Python functions
- Functions: `get_account_summaries`, `get_property_details`, `run_report`, `run_realtime_report`, `list_google_ads_links`
- All functions accept `creds` (Google OAuth credentials) as a parameter
- Property IDs use the format `properties/123456`

### Google API Helpers (`googleapi.py`)
- `get_user_email(creds)`: fetches authenticated user's email via OAuth2 userinfo API
- `get_persistent_api_key(email)` / `save_persistent_api_key(email, key)`: stores per-user Gemini API keys in `api_keys.json`

### Utility Scripts
- `list_models.py`: interactive script to check available Gemini models for a given API key
- `check_models.py`: stub/placeholder for model verification

## Key Conventions

- UTM values are normalized to lowercase, hyphens/underscores only, via `python-slugify` (`normalize_token` in app.py) and `_sanitize_utm_value` in chatbot_ui.py
- Campaign naming pattern: `Country_Type_Name_Date_CTA` (date format YYYYMMDD in builder, DD-MM-YYYY in chatbot)
- URLs are normalized to `https://www.` prefix by the chatbot
- Sensitive files (`token.json`, `client_secrets.json`, `api_keys.json`) are in `.gitignore` — requires `client_secrets.json` from Google Cloud Console to run
