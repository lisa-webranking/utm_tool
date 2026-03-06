import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import os
import json
from datetime import datetime, timedelta
from slugify import slugify
from urllib.parse import urlparse, parse_qs

import re
import html as html_lib  # per escapare valori UTM nell'HTML
from pathlib import Path

# Google Auth & Analytics import os
import google.auth
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.analytics.admin import AnalyticsAdminServiceClient
from google.analytics.data import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import RunReportRequest, DateRange, Metric, Dimension

import google.generativeai as genai
from googleapi import get_persistent_api_key, save_persistent_api_key
import ga4_mcp_tools # Import tools module
from functools import partial

# Import new Chatbot UI
from chatbot_ui import render_chatbot_interface

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Universal UTM Governance", layout="wide")

# --- CSS (STILE CLEAN + CHECKER CORRETTO) ---
st.markdown("""
<style>
    :root {
        --bg-soft: #edf4ff;
        --surface: #ffffff;
        --surface-soft: #f7fbff;
        --ink: #0f2338;
        --muted: #4f6478;
        --line: #c8d9ee;
        --brand: #0b74e5;
        --brand-strong: #0755b3;
        --accent: #00a7a0;
        --ok: #188038;
        --warn: #e37400;
        --danger: #d93025;
    }

    .stApp {
        background:
            radial-gradient(1200px 500px at 6% -10%, #dcebff 0%, rgba(220, 235, 255, 0) 60%),
            radial-gradient(900px 420px at 95% 0%, #dff8f5 0%, rgba(223, 248, 245, 0) 62%),
            var(--bg-soft);
        font-family: "Inter", "Roboto", "Segoe UI", Arial, sans-serif;
    }

    .block-container {
        max-width: 1220px;
        margin: 0 auto;
        padding-top: 1.4rem;
        padding-bottom: 2rem;
    }

    .top-shell {
        background: #ffffff;
        border: 1px solid #dbe5f0;
        border-radius: 14px;
        box-shadow: 0 4px 14px rgba(20, 36, 52, 0.06);
        padding: 16px 18px;
        margin-bottom: 14px;
    }
    .top-shell-empty {
        min-height: 8px;
    }

    .top-shell .title {
        color: #1d2731;
        font-size: 30px;
        font-weight: 700;
        margin: 0 0 4px 0;
    }

    .top-shell .subtitle {
        color: #506172;
        font-size: 14px;
        margin: 0;
    }

    .user-pill {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        border: 1px solid #d4e1ee;
        border-radius: 999px;
        background: #f4f8fc;
        color: #2f455a;
        padding: 6px 10px;
        font-size: 12px;
        font-weight: 600;
    }

    .user-avatar {
        width: 24px;
        height: 24px;
        border-radius: 50%;
        background: linear-gradient(140deg, #1f8fff, #50e3c2);
        color: #082b46;
        font-weight: 800;
        display: inline-flex;
        align-items: center;
        justify-content: center;
    }

    /* 1. Header Sezioni */
    .section-header {
        font-size: 15px; font-weight: 800; color: #213142; margin-top: 0; margin-bottom: 10px;
        text-transform: none; letter-spacing: .2px; font-family: sans-serif;
    }
    
    /* 2. Messaggi Validazione */
    .msg-error { color: var(--danger); font-size: 13px; margin-top: -5px; margin-bottom: 5px; display: flex; align-items: center; gap: 5px; }
    .msg-warning { color: var(--warn); font-size: 13px; margin-top: -5px; margin-bottom: 5px; display: flex; align-items: center; gap: 5px; }
    .msg-success { color: var(--ok); font-size: 13px; margin-top: -5px; margin-bottom: 5px; display: flex; align-items: center; gap: 5px; font-weight: 500; }
    
    /* 3. Output Box Builder */
    .output-box-ready { background-color: #e8f0fe; color: #174ea6; padding: 15px; border-radius: 8px; border: 1px solid #d2e3fc; }
    .output-box-success { background-color: #e6f4ea; color: #137333; padding: 15px; border-radius: 8px; border: 1px solid #ceead6; }

    .hero {
        background:
            radial-gradient(700px 260px at 10% 0%, rgba(120, 212, 255, 0.20), transparent 60%),
            radial-gradient(700px 260px at 90% 0%, rgba(123, 154, 255, 0.16), transparent 60%),
            linear-gradient(180deg, #f8fbff 0%, #f2f7ff 100%);
        border: 1px solid #d8e6fb;
        border-radius: 18px;
        padding: 34px 30px 26px 30px;
        box-shadow: 0 8px 22px rgba(37, 58, 89, 0.08);
        margin: 10px 0 14px 0;
        text-align: center;
    }

    .hero-title {
        font-size: 48px;
        line-height: 1.05;
        font-weight: 800;
        color: #10243a;
        margin-bottom: 10px;
    }

    .hero-sub {
        font-size: 20px;
        color: #1f3a58;
        font-weight: 600;
        margin-bottom: 12px;
        text-transform: none;
    }

    .hero-desc {
        max-width: 960px;
        margin: 0 auto 18px auto;
        font-size: 15px;
        color: #42566f;
        line-height: 1.55;
    }

    .chip-row {
        display: flex;
        justify-content: center;
        flex-wrap: wrap;
        gap: 8px;
        margin-bottom: 8px;
    }

    .chip {
        display: inline-flex;
        align-items: center;
        padding: 6px 10px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 600;
        border: 1px solid #cfe0f6;
        color: #215b8f;
        background: #f2f7ff;
    }

    .feature-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 12px;
        margin: 0 0 12px 0;
    }

    .feature-card {
        background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
        border: 1px solid #cddff6;
        border-radius: 14px;
        padding: 14px;
        box-shadow: 0 6px 16px rgba(30, 59, 96, 0.06);
    }

    .feature-title {
        font-size: 15px;
        font-weight: 700;
        color: #173452;
        margin-bottom: 4px;
    }

    .feature-copy {
        font-size: 13px;
        color: #4e647d;
        line-height: 1.45;
    }

    .step-label {
        display: inline-block;
        font-size: 11px;
        letter-spacing: .5px;
        font-weight: 700;
        color: #27537e;
        background: #eaf3ff;
        border: 1px solid #cadef7;
        border-radius: 8px;
        padding: 4px 8px;
        margin: 2px 0 8px 0;
        text-transform: uppercase;
    }

    .form-card {
        background: linear-gradient(180deg, #ffffff 0%, #fbfdff 100%);
        border: 1px solid #c9dcef;
        border-radius: 12px;
        padding: 14px;
        margin-bottom: 14px;
        box-shadow: 0 8px 20px rgba(15, 35, 56, 0.06);
    }

    .sticky-panel {
        position: sticky;
        top: 80px;
    }

    .output-card {
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: 12px;
        padding: 14px;
        box-shadow: 0 2px 8px rgba(20, 36, 52, 0.04);
    }

    .param-chip-row {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin: 10px 0 0 0;
    }

    .param-chip {
        display: inline-flex;
        align-items: center;
        padding: 5px 8px;
        border-radius: 8px;
        font-size: 12px;
        font-weight: 600;
        border: 1px solid transparent;
    }

    .param-chip.source { background: #e7f5ef; border-color: #cdebdc; color: #1b6b45; }
    .param-chip.medium { background: #ebefff; border-color: #d5defd; color: #3a4ea8; }
    .param-chip.campaign { background: #fff3e7; border-color: #ffe2c2; color: #8a4f11; }
    .param-chip.content { background: #f0f3f6; border-color: #dfe6ee; color: #465465; }

    .tilda-panel {
        background:
            linear-gradient(180deg, #ffffff 0%, var(--surface-soft) 100%);
        border: 1px solid #c9dcef;
        border-radius: 14px;
        padding: 20px;
        margin-top: 8px;
        box-shadow: 0 10px 24px rgba(18, 43, 70, 0.06);
    }

    .tilda-title {
        font-size: 38px;
        font-weight: 700;
        color: #10263f;
        margin-bottom: 2px;
        letter-spacing: .2px;
    }

    .tilda-sub {
        font-size: 14px;
        color: #3f5b75;
        margin-bottom: 14px;
    }

    .tilda-section {
        font-size: 22px;
        font-weight: 600;
        color: #173756;
        margin: 14px 0 8px 0;
    }

    .tilda-note {
        font-size: 13px;
        color: #4a627a;
        margin: 4px 0 10px 0;
    }
    
    /* 4. STILE UTM CHECKER (Riproduzione Screenshot) */
    .utm-check-card {
        background-color: white;
        border: 1px solid #e0e0e0;
        border-radius: 5px;
        box-shadow: 0 1px 2px rgba(0,0,0,0.05);
        margin-top: 15px;
        overflow: hidden; /* Importante per i bordi */
    }
    
    .utm-row {
        display: flex;
        align-items: center;
        border-bottom: 1px solid #e9ecef;
        padding: 12px 15px;
    }
    
    .utm-row:last-child {
        border-bottom: none;
    }
    
    /* Colonna Etichetta (Tag) */
    .utm-label-col {
        width: 160px;
        flex-shrink: 0;
    }
    
    .utm-tag {
        display: inline-block;
        padding: 6px 12px;
        border-radius: 4px;
        color: white;
        font-weight: 600;
        font-size: 13px;
        text-align: center;
        min-width: 110px;
    }
    
    .tag-blue { background-color: #0077c8; } 
    .tag-gray { background-color: #6c757d; } 
    
    /* Colonna Valore */
    .utm-value-col {
        flex-grow: 1;
        font-size: 15px;
        color: #333;
        display: flex;
        align-items: center;
        gap: 10px;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    
    .check-icon { color: #28a745; font-weight: bold; font-size: 18px; }
    .error-icon { color: #dc3545; font-weight: bold; font-size: 18px; }
    .error-text { color: #dc3545; font-weight: 500; font-size: 14px; font-style: italic; }

    .status-badge {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 999px;
        padding: 4px 10px;
        font-size: 11px;
        font-weight: 700;
        border: 1px solid transparent;
    }

    .badge-ok { background: #e7f5ec; color: #1a7a43; border-color: #cdebd9; }
    .badge-warn { background: #fff2e6; color: #9f5b00; border-color: #ffddb8; }
    .badge-bad { background: #fdeced; color: #a32828; border-color: #f6c9cc; }
    .badge-opt { background: #eff3f7; color: #4f6071; border-color: #dbe3eb; }

    .checks-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
        margin-top: 8px;
    }

    .checks-item {
        border: 1px solid var(--line);
        border-radius: 10px;
        background: #fff;
        padding: 10px;
    }

    .checks-label {
        font-size: 12px;
        color: #4e5d6c;
        margin-bottom: 6px;
        font-weight: 600;
    }

    .utm-compact-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
        margin-top: 8px;
    }

    .utm-param-item {
        border: 1px solid var(--line);
        border-radius: 10px;
        padding: 10px;
        background: #fff;
    }

    .utm-param-title {
        font-size: 12px;
        font-weight: 700;
        color: #2f3f4f;
        margin-bottom: 6px;
    }

    .utm-param-value {
        font-size: 13px;
        color: #1f2933;
        word-break: break-word;
        margin-top: 6px;
    }

    /* 5. STILE CHAT GEMINI (Riproduzione) */
    .gemini-container {
        max-width: 800px;
        margin: 0 auto;
        padding: 20px;
    }
    
    .gemini-msg {
        margin-bottom: 24px;
        font-family: 'Google Sans', Roboto, Arial, sans-serif;
        font-size: 16px;
        line-height: 1.5;
        color: #1f1f1f;
    }
    
    .gemini-msg-user {
        display: flex;
        flex-direction: column;
        align-items: flex-end;
    }
    
    .gemini-msg-user .bubble {
        background-color: #f0f4f9;
        padding: 12px 20px;
        border-radius: 18px;
        max-width: 85%;
        word-wrap: break-word;
    }
    
    .gemini-msg-assistant {
        display: flex;
        gap: 16px;
        align-items: flex-start;
    }
    
    .gemini-msg-assistant .avatar {
        width: 30px;
        height: 30px;
        background: linear-gradient(135deg, #4285f4, #9b72cb, #d96570);
        border-radius: 50%;
        flex-shrink: 0;
        margin-top: 4px;
    }
    
    .gemini-msg-assistant .content {
        flex-grow: 1;
        padding-top: 2px;
    }

    /* Override Streamlit Chat Input to look more like Gemini */
    .stChatInputContainer {
        border-radius: 28px !important;
        border: 1px solid #757575 !important;
        background-color: white !important;
        max-width: 800px !important;
        margin: 0 auto !important;
    }

    div[data-testid="stWidgetLabel"] p {
        color: #243342 !important;
        font-weight: 620 !important;
        font-size: 0.94rem !important;
    }

    div[data-testid="stTabs"] [data-baseweb="tab-list"],
    div[data-testid="stTabs"] [role="tablist"] {
        display: flex !important;
        justify-content: center !important;
        align-items: center !important;
        gap: 10px;
        background: linear-gradient(180deg, #eef5ff 0%, #e8f1fe 100%) !important;
        border: 1px solid #c8d9ee !important;
        border-radius: 999px;
        padding: 6px 8px;
        width: fit-content;
        margin: 8px auto 12px auto;
    }

    div[data-testid="stTabs"] > div,
    div[data-testid="stTabs"] > div > div,
    div[data-testid="stTabs"] [data-baseweb="tab-border"] {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        padding: 0 !important;
    }
    div[data-testid="stTabs"] [data-baseweb="tab-highlight"] {
        display: none !important;
    }
    div[data-testid="stTabs"] [role="tabpanel"] {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        padding-top: 0 !important;
    }

    div[data-testid="stTabs"] [data-baseweb="tab"],
    div[data-testid="stTabs"] [role="tab"] {
        border-radius: 999px;
        padding: 9px 18px;
        font-weight: 700;
        color: #27425d;
        border: 1px solid transparent;
        background: transparent;
        transition: all .2s ease;
    }

    div[data-testid="stTabs"] [aria-selected="true"] {
        background: linear-gradient(120deg, var(--brand), var(--brand-strong));
        color: #fff !important;
        border-color: #0b63c7;
        box-shadow: 0 6px 14px rgba(11, 116, 229, 0.3);
    }

    div[data-testid="stTabs"] [data-baseweb="tab"]:hover,
    div[data-testid="stTabs"] [role="tab"]:hover {
        background: #f6faff;
        border-color: #c8d9ee;
    }

    .stButton > button {
        border-radius: 10px;
        border: 1px solid #bcd2ea;
        background: #f6fbff;
        color: #1d3955;
        font-weight: 600;
    }

    .stButton > button[kind="primary"] {
        background: linear-gradient(120deg, var(--brand), var(--brand-strong));
        border: none;
        color: #fff;
        font-weight: 700;
    }

    /* Allinea altezza e migliora leggibilità dei campi */
    div[data-testid="stTextInput"] input,
    div[data-baseweb="select"] > div,
    div[data-testid="stDateInput"] input {
        min-height: 42px !important;
        border-radius: 10px !important;
        border: 1px solid #b9d2ea !important;
        background: #ffffff !important;
        color: #12283f !important;
        box-shadow: inset 0 1px 0 rgba(255,255,255,.6) !important;
    }

    div[data-testid="stTextInput"] input::placeholder {
        color: #7d95ab !important;
    }

    div[data-baseweb="select"] > div {
        background: #ffffff !important;
    }

    div[data-testid="stTextInput"] input:focus,
    div[data-baseweb="select"] > div:focus-within,
    div[data-testid="stDateInput"] input:focus {
        border-color: var(--brand) !important;
        box-shadow: 0 0 0 3px rgba(11, 116, 229, 0.16) !important;
    }

    /* Campi disabilitati (es. label utm_*) volutamente differenziati */
    div[data-testid="stTextInput"] input:disabled {
        background: linear-gradient(180deg, #dce9f9 0%, #cfdef2 100%) !important;
        border: 1px solid #a9c2de !important;
        color: #2f4d69 !important;
        font-weight: 600 !important;
    }

    div[data-testid="stTextInput"] label,
    div[data-testid="stSelectbox"] label,
    div[data-testid="stDateInput"] label {
        color: #23415e !important;
        font-weight: 620 !important;
    }

    @media (max-width: 900px) {
        .feature-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }

        .checks-grid,
        .utm-compact-grid {
            grid-template-columns: 1fr;
        }

        .sticky-panel {
            position: static;
        }

        .hero-title {
            font-size: 34px;
        }

        .hero-sub {
            font-size: 18px;
        }
    }

    @media (max-width: 640px) {
        .feature-grid {
            grid-template-columns: 1fr;
        }
    }

</style>
""", unsafe_allow_html=True)

# --- GOOGLE AUTH FUNCTIONS ---
SCOPES = [
    'https://www.googleapis.com/auth/analytics.readonly',
    'https://www.googleapis.com/auth/analytics.edit',
    'https://www.googleapis.com/auth/userinfo.email',
    'openid'
]

def get_oauth_flow():
    """Configura l'oggetto Flow per Web OAuth usando i Secrets o il json locale"""
    # Prova a prendere le configurazioni dai Secrets di Streamlit
    if "gcp_service_account" in st.secrets:
        # Se c'è un service account configurato nei secrets, potresti saltare OAuth, 
        # ma per il flusso utente richiesto presupponiamo OAuth Client ID Web App.
        # Fallback al json locale per la configurazione se nei secrets mettiamo l'intero JSON client_secrets
        pass
    
    # Per ora gestiamo il file locale o i secrets (se configurati come dict nel toml)
    base_path = os.path.dirname(os.path.abspath(__file__))
    secrets_path = os.path.join(base_path, 'client_secrets.json')
    
    # Determina la redirect URI dinamica dalla URL dell'app Streamlit, o usa un default
    # Notare che Streamlit Cloud su redirect tipicamente usa l'URL base.
    # In locale useremo http://localhost:8501
    
    # Ottieni i parametri attuali per capire se siamo in callback
    query_params = st.query_params
    
    if os.path.exists(secrets_path):
        import json
        with open(secrets_path, 'r') as f:
            client_config = json.load(f)
    elif "google_oauth" in st.secrets:
        # Crea dict dal toml
        client_config = {"web": dict(st.secrets["google_oauth"])}
    else:
        st.error("Configurazione OAuth (client_secrets.json o st.secrets) mancante!")
        return None

    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES
    )
    
    # Costruisci redirect_uri base 
    # (Attenzione: DEVE coincidere esattamente con quella registrata per l'app su Google Cloud)
    # Su Streamlit Cloud è un po' tricky ottenere il proprio URL dinamicamente via codice in modo affidabile,
    # quindi se impostato in st.secrets["redirect_uri"] usiamo quello, altrimenti cerchiamo di indovinarlo.
    if "redirect_uri" in st.secrets:
        redirect_uri = st.secrets["redirect_uri"]
    else:
        # Assume test locale
        redirect_uri = 'http://localhost:8501/'
        
    flow.redirect_uri = redirect_uri
    return flow

def do_oauth_flow():
    """Gestisce il flow di autenticazione Google OAuth 2.0 Web"""
    
    # Controlla se le credenziali sono già in sessione
    if 'google_credentials' in st.session_state and st.session_state.google_credentials:
        creds = Credentials(
            token=st.session_state.google_credentials['token'],
            refresh_token=st.session_state.google_credentials.get('refresh_token'),
            token_uri=st.session_state.google_credentials.get('token_uri'),
            client_id=st.session_state.google_credentials.get('client_id'),
            client_secret=st.session_state.google_credentials.get('client_secret'),
            scopes=st.session_state.google_credentials.get('scopes')
        )
        
        if creds.valid:
            return creds
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                # Aggiorna sessione
                st.session_state.google_credentials['token'] = creds.token
                return creds
            except Exception:
                st.session_state.google_credentials = None
                
    # Verifica se stiamo tornando da un redirect di login
    query_params = st.query_params
    if 'code' in query_params:
        flow = get_oauth_flow()
        if not flow:
            return None
            
        try:
            # Recupera il token
            code = query_params['code']
            flow.fetch_token(code=code)
            creds = flow.credentials
            
            # Salva credenziali scalari compatibili con JSON in session_state, NO file
            st.session_state.google_credentials = {
                'token': creds.token,
                'refresh_token': creds.refresh_token,
                'token_uri': creds.token_uri,
                'client_id': creds.client_id,
                'client_secret': creds.client_secret,
                'scopes': creds.scopes
            }
            
            # Ripulisci l'URL (rimuovi ?code=...) così se refresha la pagina non va in crash
            import urllib.parse
            if hasattr(st, "query_params"):
                st.query_params.clear()
            else:
                st.experimental_set_query_params() # per vecchie versioni streamlit
                
            st.rerun() # Forza rerun per mostrare UI pulita
        except Exception as e:
            st.error(f"Errore durante l'accesso: {e}")
            
    # Se arriva qui, serve fare il login
    return None

def get_ga4_accounts_structure(creds):
    """Recupera la struttura Account -> Properties usando ga4_mcp_tools"""
    try:
        # Usa la funzione centralizzata che ritorna già la gerarchia
        return ga4_mcp_tools.get_account_summaries(creds)
    except Exception as e:
        st.error(f"Errore nel recupero property: {e}")
        return []

def get_top_traffic_sources(property_id, creds):
    """Recupera le sorgenti di traffico principali degli ultimi 30 giorni"""
    try:
        client = BetaAnalyticsDataClient(credentials=creds)
        request = RunReportRequest(
            property=property_id,
            date_ranges=[DateRange(start_date="30daysAgo", end_date="today")],
            dimensions=[Dimension(name="sessionSource")],
            metrics=[Metric(name="sessions")],
            limit=50
        )
        response = client.run_report(request)
        
        sources = []
        for row in response.rows:
            sources.append(row.dimension_values[0].value)
        return sources
    except Exception as e:
        st.warning(f"Impossibile recuperare sorgenti da GA4: {e}")
        return []

def get_top_traffic_mediums(property_id, creds):
    """Recupera i medium principali degli ultimi 30 giorni"""
    try:
        client = BetaAnalyticsDataClient(credentials=creds)
        request = RunReportRequest(
            property=property_id,
            date_ranges=[DateRange(start_date="30daysAgo", end_date="today")],
            dimensions=[Dimension(name="sessionMedium")],
            metrics=[Metric(name="sessions")],
            limit=50
        )
        response = client.run_report(request)
        mediums = []
        for row in response.rows:
            mediums.append(row.dimension_values[0].value)
        return mediums
    except Exception as e:
        st.warning(f"Impossibile recuperare medium da GA4: {e}")
        return []

def get_source_medium_pairs(property_id, creds):
    """Recupera coppie source-medium principali degli ultimi 30 giorni."""
    try:
        client = BetaAnalyticsDataClient(credentials=creds)
        request = RunReportRequest(
            property=property_id,
            date_ranges=[DateRange(start_date="30daysAgo", end_date="today")],
            dimensions=[Dimension(name="sessionSource"), Dimension(name="sessionMedium")],
            metrics=[Metric(name="sessions")],
            limit=200
        )
        response = client.run_report(request)
        pairs = []
        for row in response.rows:
            src = row.dimension_values[0].value
            med = row.dimension_values[1].value
            pairs.append((src, med))
        return pairs
    except Exception as e:
        st.warning(f"Impossibile recuperare coppie source-medium da GA4: {e}")
        return []

# --- DATI GUIDA (Fallback e Mapping) ---
GUIDE_TABLE_DATA = [
    {"Traffic type": "Organic", "utm_medium": "organic", "utm_source": "google, bing, yahoo"},
    {"Traffic type": "Referral", "utm_medium": "referral", "utm_source": "(domain)"},
    {"Traffic type": "Direct", "utm_medium": "(none)", "utm_source": "(direct)"},
    {"Traffic type": "Paid Search", "utm_medium": "cpc", "utm_source": "google, bing"},
    {"Traffic type": "Affiliate", "utm_medium": "affiliate", "utm_source": "tradetracker, awin"},
    {"Traffic type": "Display", "utm_medium": "cpm", "utm_source": "reservation, display, dv360, google"},
    {"Traffic type": "Video", "utm_medium": "cpv", "utm_source": "youtube, vimeo, google"},
    {"Traffic type": "Programmatic", "utm_medium": "cpm", "utm_source": "rcs, mediamond, rai, manzoni"},
    {"Traffic type": "Email", "utm_medium": "email|mailing_campaign", "utm_source": "newsletter, email, crm, sfmc, mailchimp"},
    {"Traffic type": "Organic Social", "utm_medium": "social_org", "utm_source": "facebook, instagram, tiktok, linkedin, pinterest"},
    {"Traffic type": "Paid Social", "utm_medium": "social_paid", "utm_source": "facebook, instagram, tiktok, linkedin, pinterest"},
    {"Traffic type": "App traffic", "utm_medium": "-", "utm_source": "app"},
    {"Traffic type": "SMS", "utm_medium": "offline", "utm_source": "sms"},
    {"Traffic type": "Altro", "utm_medium": "other", "utm_source": ""},
]

# --- UTILS ---
def get_source_options():
    sources = set()
    for row in GUIDE_TABLE_DATA:
        parts = row["utm_source"].split(",")
        for p in parts:
            clean = p.strip().replace("...", "")
            if clean and "(" not in clean and "[" not in clean:
                sources.add(clean)
    return [""] + sorted(list(sources)) + ["Altro (Inserisci manuale)"]

SOURCE_OPTIONS = get_source_options()

def get_compatible_channels(selected_source, all_client_channels):
    if not selected_source or selected_source == "Altro (Inserisci manuale)":
        return [""] + all_client_channels
    norm_source = selected_source.strip().lower()
    compatible_types = set()
    for row in GUIDE_TABLE_DATA:
        row_sources = [s.strip().lower() for s in row["utm_source"].split(",")]
        if norm_source in row_sources:
            compatible_types.add(row["Traffic type"])
    if not compatible_types:
        return [""] + all_client_channels
    filtered_channels = [c for c in all_client_channels if c in compatible_types]
    return [""] + sorted(filtered_channels) if filtered_channels else [""] + all_client_channels

def normalize_token(text):
    if not text: return ""
    return slugify(text, separator="-", lowercase=True)

def normalize_medium_token(text):
    """Normalizza utm_medium preservando underscore GA4 (es. social_paid)."""
    if not text:
        return ""
    value = str(text).strip().lower()
    value = value.replace("-", "_")
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"[^a-z0-9_-]", "", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value

def suggest_naming_value(text, prefer_hyphen=True):
    """Produce a best-practice suggestion for campaign naming values."""
    if not text:
        return ""
    value = str(text).strip().lower()
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"[^a-z0-9_-]", "", value)
    if prefer_hyphen:
        value = value.replace("_", "-")
    value = re.sub(r"-{2,}", "-", value)
    value = re.sub(r"_{2,}", "_", value)
    return value.strip("-_")

def validate_naming_rules(text, prefer_hyphen=True):
    """Return (issues, suggestion) for naming best-practices validation."""
    issues = []
    if not text:
        return issues, ""
    raw = str(text).strip()
    suggestion = suggest_naming_value(raw, prefer_hyphen=prefer_hyphen)

    if raw != raw.lower():
        issues.append("usa solo minuscole")
    if re.search(r"\s", raw):
        issues.append("evita spazi")
    if re.search(r"[^A-Za-z0-9_-]", raw):
        issues.append("evita caratteri speciali")
    if prefer_hyphen and "_" in raw:
        issues.append("preferisci trattini (-) agli underscore (_)")
    if len(raw) > 50:
        issues.append("mantieni il nome descrittivo ma conciso")
    return issues, suggestion

def filter_options_by_source_mode(options, mode, field):
    """Filter source/medium options according to selected traffic source mode."""
    if field == "medium":
        tokens = [normalize_medium_token(o) for o in options if normalize_medium_token(o)]
    else:
        tokens = [normalize_token(o) for o in options if normalize_token(o)]
    if mode == "Custom values":
        return sorted(set(tokens))

    if field == "source":
        source_map = {
            "Google Ads": ["google", "adwords", "googleads", "bing"],
            "Social": ["facebook", "instagram", "tiktok", "linkedin", "pinterest", "social", "meta", "twitter", "x"],
            "Email": ["email", "newsletter", "crm", "mailchimp", "sfmc"],
        }
        hints = source_map.get(mode, [])
    else:
        medium_map = {
            "Google Ads": ["cpc", "ppc", "paid-search", "paid_search", "sem"],
            "Social": ["social", "social_paid", "social_org", "paid-social", "organic-social", "organic_social", "paid_social"],
            "Email": ["email", "mailing_campaign", "newsletter", "mail"],
        }
        hints = medium_map.get(mode, [])

    filtered = [t for t in tokens if any(h in t for h in hints)]
    return sorted(set(filtered))

def is_valid_url(url):
    regex = re.compile(r'^https?://(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|localhost|\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?::\d+)?(?:/?|[/?]\S+)$', re.IGNORECASE)
    return re.match(regex, url) is not None

def load_utm_history():
    if 'utm_history' not in st.session_state:
        st.session_state.utm_history = []
    return st.session_state.utm_history

def save_utm_history(items):
    st.session_state.utm_history = items

def infer_expected_channel_group(utm_medium: str) -> str:
    m = normalize_medium_token(utm_medium)
    if m in ("social_paid", "paid_social", "paid-social"):
        return "Paid Social"
    if m in ("social_org", "organic_social", "organic-social"):
        return "Organic Social"
    if m in ("email", "mailing_campaign", "newsletter"):
        return "Email"
    if m in ("cpc", "ppc", "sem", "paid_search", "paid-search"):
        return "Paid Search"
    if m in ("cpm", "display"):
        return "Display"
    if m == "referral":
        return "Referral"
    if m == "organic":
        return "Organic Search"
    return "Other"

def upsert_utm_history_entry(entry: dict):
    items = load_utm_history()
    key_fields = ("user_email", "property_id", "final_url")
    idx = next(
        (i for i, x in enumerate(items) if all(x.get(k) == entry.get(k) for k in key_fields)),
        None
    )
    if idx is None:
        items.append(entry)
    else:
        items[idx].update(entry)
    save_utm_history(items)

def parse_ddmmyyyy_to_date(date_str: str):
    try:
        return datetime.strptime(date_str, "%d/%m/%Y").date()
    except Exception:
        return None

def _extract_live_date_from_utm_campaign(utm_campaign: str) -> str:
    campaign = (utm_campaign or "").strip().lower()
    for token in campaign.split("_"):
        if re.fullmatch(r"\d{8}", token):
            try:
                dt = datetime.strptime(token, "%d%m%Y")
                return dt.strftime("%d/%m/%Y")
            except Exception:
                continue
    return datetime.today().strftime("%d/%m/%Y")

def save_chatbot_url_to_history(final_url: str, property_id: str = "") -> bool:
    try:
        parsed = urlparse((final_url or "").strip())
        if not parsed.scheme or not parsed.netloc:
            return False
        params = parse_qs(parsed.query)

        utm_source = normalize_token((params.get("utm_source") or [""])[0])
        utm_medium = normalize_medium_token((params.get("utm_medium") or [""])[0])
        utm_campaign = normalize_token((params.get("utm_campaign") or [""])[0])
        if not (utm_source and utm_medium and utm_campaign):
            return False

        campaign_parts = [p for p in utm_campaign.split("_") if p]
        campaign_name = campaign_parts[2] if len(campaign_parts) >= 3 else utm_campaign
        live_date = _extract_live_date_from_utm_campaign(utm_campaign)

        prop_lookup = build_property_name_lookup(st.session_state.get("ga4_accounts", []))
        prop_id_raw = str(property_id or "").replace("properties/", "")
        property_name = (
            prop_lookup.get(str(property_id or ""))
            or prop_lookup.get(prop_id_raw)
            or ""
        )

        entry = {
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "user_email": st.session_state.get("user_email", ""),
            "property_id": prop_id_raw,
            "property_name": property_name,
            "campaign_name": campaign_name,
            "live_date": live_date,
            "utm_source": utm_source,
            "utm_medium": utm_medium,
            "utm_campaign": utm_campaign,
            "final_url": final_url,
            "expected_channel_group": infer_expected_channel_group(utm_medium),
        }
        upsert_utm_history_entry(entry)
        return True
    except Exception:
        return False

def build_property_name_lookup(accounts_structure):
    lookup = {}
    if not isinstance(accounts_structure, list):
        return lookup
    for acc in accounts_structure:
        for p in acc.get("properties", []) or []:
            pid_raw = str(p.get("property_id", "")).strip()
            if not pid_raw:
                continue
            pid_num = pid_raw.replace("properties/", "")
            name = p.get("display_name", "")
            if name:
                lookup[pid_raw] = name
                lookup[pid_num] = name
    return lookup

def check_tracking_status_for_entry(entry: dict, creds, grace_days: int = 2):
    property_id = entry.get("property_id")
    if not property_id:
        return {"status": "ERROR", "message": "Property non disponibile", "sessions": 0, "observed": "-"}
    try:
        client = BetaAnalyticsDataClient(credentials=creds)
        ga4_prop = property_id if str(property_id).startswith("properties/") else f"properties/{property_id}"
        report = client.run_report(
            RunReportRequest(
                property=ga4_prop,
                date_ranges=[DateRange(start_date="30daysAgo", end_date="today")],
                dimensions=[
                    Dimension(name="sessionSource"),
                    Dimension(name="sessionMedium"),
                    Dimension(name="sessionCampaignName"),
                    Dimension(name="sessionPrimaryChannelGroup"),
                    Dimension(name="sessionDefaultChannelGroup"),
                ],
                metrics=[Metric(name="sessions")],
                limit=1000,
            )
        )
        src = normalize_token(entry.get("utm_source", ""))
        med = normalize_medium_token(entry.get("utm_medium", ""))
        cmpn = normalize_token(entry.get("utm_campaign", ""))

        matched = []
        for row in report.rows:
            ds = normalize_token(row.dimension_values[0].value)
            dm = normalize_medium_token(row.dimension_values[1].value)
            dc = normalize_token(row.dimension_values[2].value)
            sessions = int(float(row.metric_values[0].value or 0))
            observed = row.dimension_values[3].value or row.dimension_values[4].value or "Unassigned"
            if ds == src and dm == med and dc == cmpn:
                matched.append((sessions, observed))

        total_sessions = sum(x[0] for x in matched)
        observed_channel = "-"
        if matched:
            by_channel = {}
            for s, ch in matched:
                by_channel[ch] = by_channel.get(ch, 0) + s
            observed_channel = sorted(by_channel.items(), key=lambda x: x[1], reverse=True)[0][0]

        expected = entry.get("expected_channel_group", "Other")
        live_date = parse_ddmmyyyy_to_date(entry.get("live_date", ""))
        today = datetime.today().date()
        after_grace = bool(live_date and today > (live_date + timedelta(days=grace_days)))

        if total_sessions == 0 and after_grace:
            return {
                "status": "ERROR",
                "message": "Nessun traffico rilevato con questi UTM",
                "sessions": 0,
                "observed": observed_channel,
            }
        if total_sessions > 0 and observed_channel != expected:
            return {
                "status": "WARNING",
                "message": f"Il traffico è finito in {observed_channel} invece di {expected}",
                "sessions": total_sessions,
                "observed": observed_channel,
            }
        if total_sessions > 0 and observed_channel == expected:
            return {
                "status": "OK",
                "message": "Tracking e canalizzazione corretti",
                "sessions": total_sessions,
                "observed": observed_channel,
            }
        return {
            "status": "PENDING",
            "message": "Campagna recente: in attesa di traffico",
            "sessions": total_sessions,
            "observed": observed_channel,
        }
    except Exception as e:
        return {"status": "ERROR", "message": f"Errore GA4: {e}", "sessions": 0, "observed": "-"}

# --- LOGIN PAGE ---
def show_login_page():
    st.container()
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.markdown("<div style='text-align: center; margin-top: 100px;'>", unsafe_allow_html=True)
        st.title("🛡️ Universal UTM Governance")
        st.subheader("Accedi per gestire i tuoi link")
        st.markdown("</div>", unsafe_allow_html=True)
        
        st.write("")
        st.write("")
        
        # Link OAuth generato web-side (PKCE bypass using manual config for Server-Side Web App)
        flow = get_oauth_flow()
        if flow:
            # Bypass autogenerated pkce enforcing by the library specifically for web server flows 
            # where session states are lost in cross-domain redirects
            auth_url, _ = flow.authorization_url(
                access_type='offline',
                prompt='consent',
                include_granted_scopes='true'
            )
            # Remove PKCE enforcement directly from the flow object so fetch_token doesn't look for it
            flow.code_verifier = None 

            st.link_button("🔐 Login con Google Analytics", auth_url, type="primary", use_container_width=True)
        else:
            st.error("Configurazione Google Auth mancante.")

# --- DASHBOARD PAGE ---
def show_dashboard():
    # --- INITIALIZE USER EMAIL AND API KEY ---
    if "user_email" not in st.session_state:
        st.session_state.user_email = get_user_email(st.session_state.credentials)
    
    if "gemini_api_key" not in st.session_state:
        # Try to load saved API key for this user
        saved_key = get_persistent_api_key(st.session_state.user_email)
        st.session_state.gemini_api_key = saved_key
    
    # --- HEADER PRINCIPALE ---
    if "show_user_menu" not in st.session_state:
        st.session_state.show_user_menu = False

    _, c_head_2 = st.columns([4.0, 1.2])
    with c_head_2:
        user_email = st.session_state.get("user_email", "")
        user_initial = user_email[:1].upper() if user_email else "U"
        st.markdown(
            f'<div class="user-pill"><span class="user-avatar">{user_initial}</span>{html_lib.escape(user_email)}</div>',
            unsafe_allow_html=True
        )
        if hasattr(st, "popover"):
            with st.popover("Account ▾", use_container_width=True):
                if st.button("Impostazioni", key="settings_btn_menu", use_container_width=True):
                    st.session_state.show_settings = True
                if st.button("Logout", key="logout_btn", use_container_width=True):
                    if "credentials" in st.session_state:
                        del st.session_state.credentials
                    if "user_email" in st.session_state:
                        del st.session_state.user_email
                    if "gemini_api_key" in st.session_state:
                        del st.session_state.gemini_api_key
                    if "google_credentials" in st.session_state:
                        del st.session_state.google_credentials
                    st.rerun()
        else:
            if st.button("Account ▾", key="user_menu_btn", use_container_width=True):
                st.session_state.show_user_menu = not st.session_state.show_user_menu
            if st.session_state.show_user_menu:
                if st.button("Impostazioni", key="settings_btn_menu_fallback", use_container_width=True):
                    st.session_state.show_settings = not st.session_state.get("show_settings", False)
                    st.session_state.show_user_menu = False
                if st.button("Logout", key="logout_btn_fallback", use_container_width=True):
                    if "credentials" in st.session_state:
                        del st.session_state.credentials
                    if "user_email" in st.session_state:
                        del st.session_state.user_email
                    if "gemini_api_key" in st.session_state:
                        del st.session_state.gemini_api_key
                    if "google_credentials" in st.session_state:
                        del st.session_state.google_credentials
                    st.rerun()

    # --- SETTINGS MODAL ---
    if st.session_state.get("show_settings", False):
        st.markdown('<div class="form-card">', unsafe_allow_html=True)
        s_col1, s_col2 = st.columns([0.92, 0.08])
        with s_col1:
            st.markdown("### ⚙️ Impostazioni")
        with s_col2:
            if st.button("✕", key="close_settings_top", help="Chiudi impostazioni", use_container_width=True):
                st.session_state.show_settings = False
                st.rerun()
        with st.container():
            st.markdown("### Configurazione Gemini API")
            st.markdown(f"**Account:** {st.session_state.user_email}")
            
            current_key = st.session_state.get("gemini_api_key", "")
            key_status = "✅ Configurata" if current_key else "❌ Non configurata"
            st.markdown(f"**Stato API Key:** {key_status}")
            
            with st.form("api_key_form"):
                new_api_key = st.text_input(
                    "Gemini API Key",
                    value=current_key if current_key else "",
                    type="password",
                    help="Inserisci la tua chiave API di Google Gemini"
                )
                col1, col2 = st.columns([1, 1])
                with col1:
                    save_btn = st.form_submit_button("💾 Salva", use_container_width=True)
                with col2:
                    close_btn = st.form_submit_button("Chiudi", use_container_width=True)
                
                if save_btn and new_api_key:
                    st.session_state.gemini_api_key = new_api_key
                    save_persistent_api_key(st.session_state.user_email, new_api_key)
                    st.success("✅ API Key salvata con successo!")
                    st.session_state.show_settings = False
                    st.rerun()
                
                if close_btn:
                    st.session_state.show_settings = False
                    st.rerun()
            
            # --- GA4 Diagnostics ---
            st.markdown("---")
            st.markdown("### 🔌 Connessione GA4")
            if st.button("🔁 Test connessione GA4", key="test_ga4_btn"):
                with st.spinner("Verifica connessione GA4..."):
                    result = ga4_mcp_tools.get_account_summaries(st.session_state.credentials)
                if isinstance(result, list) and len(result) > 0:
                    st.success(f"✅ Connessione GA4 OK! Trovati {len(result)} account.")
                elif isinstance(result, list) and len(result) == 0:
                    st.warning("⚠️ Connessione OK ma nessun account GA4 trovato per questo utente.")
                elif isinstance(result, dict) and "error" in result:
                    error_type = result.get("error_type", "Sconosciuto")
                    error_msg = result.get("error", "")
                    st.error(f"❌ Errore GA4\n\n**Tipo:** {error_type}\n\n**Dettaglio:** {error_msg}")
                    if any(kw in error_msg.lower() for kw in ["credentials", "scope", "permission", "unauthenticated", "unauthorized", "403", "401"]):
                        st.warning("💡 Il token OAuth potrebbe avere scope insufficienti. Prova a fare **Logout** e ri-accedere con Google.")
                else:
                    st.info(f"Risposta inattesa: {result}")
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("""
    <div class="hero">
        <div class="hero-title">Smart UTM Assistant</div>
        <div class="hero-sub">Il collegamento live a GA4 e il chatbot ti guideranno nella creazione</div>
        <div class="hero-desc">Questo tool ti permette di creare e validare link UTM con una guida passo-passo del chatbot, mentre legge in tempo reale la property GA4 selezionata per mostrarti sorgenti e convenzioni realmente usate nelle campagne.</div>
        <div class="chip-row">
            <span class="chip">Guida chatbot step-by-step</span>
            <span class="chip">Connessione diretta GA4</span>
            <span class="chip">Dati reali di campagna</span>
        </div>
    </div>
    <div class="feature-grid">
        <div class="feature-card">
            <div class="feature-title">Guida Assistita</div>
            <div class="feature-copy">Il chatbot ti accompagna passo-passo nella compilazione corretta dei parametri.</div>
        </div>
        <div class="feature-card">
            <div class="feature-title">Live Data GA4</div>
            <div class="feature-copy">Source e medium vengono letti in tempo reale dalla property GA4 selezionata.</div>
        </div>
        <div class="feature-card">
            <div class="feature-title">Standard Operativo</div>
            <div class="feature-copy">Generi URL UTM uniformi e coerenti con le convenzioni reali di campagna.</div>
        </div>
        <div class="feature-card">
            <div class="feature-title">Vantaggio Reale</div>
            <div class="feature-copy">Diverso dai builder classici: qui hai GA4 collegato + assistente guidato nello stesso flusso.</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    # --- TABS DI NAVIGAZIONE ---
    tab_builder, tab_checker, tab_history = st.tabs(["Build URL", "Check URL", "UTM History & Tracking"])

    # --- SESSION STATE PER CHAT ---
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # ==============================================================================
    # TAB 1: UTM GENERATOR (BUILDER)
    # ==============================================================================
    with tab_builder:
        st.markdown('<div class="tilda-title">Campaign URL Builder</div>', unsafe_allow_html=True)
        st.markdown('<div class="tilda-sub">Seleziona la property GA4 di riferimento per caricare source e medium reali.</div>', unsafe_allow_html=True)

        selected_prop_name = None
        sel_prop_id = None
        prop_channels = ["Paid Search", "Paid Social", "Display", "Email", "Organic Social", "Affiliate", "Video", "Altro"]
        prop_config = {"default_country": "it", "expected_domain": ""}
        real_sources = []
        real_mediums = []
        source_medium_map = {}

        ga_col1, ga_col2 = st.columns([1.2, 1], gap="small")
        if "ga4_accounts" not in st.session_state:
            with st.spinner("Caricamento Account GA4..."):
                st.session_state.ga4_accounts = get_ga4_accounts_structure(st.session_state.credentials)
        accounts_structure = st.session_state.ga4_accounts
        if accounts_structure:
            account_names = [a["display_name"] for a in accounts_structure]
            with ga_col1:
                selected_account_name = st.selectbox("GA4 Account", account_names)
            selected_account = next((a for a in accounts_structure if a["display_name"] == selected_account_name), None)
            if selected_account and selected_account["properties"]:
                prop_map = {p["display_name"]: p["property_id"] for p in selected_account["properties"]}
                with ga_col2:
                    selected_prop_name = st.selectbox("GA4 Property", list(prop_map.keys()))
                if selected_prop_name:
                    sel_prop_id = prop_map[selected_prop_name]
                    current_prop_key = f"sources_{sel_prop_id}"
                    if current_prop_key not in st.session_state:
                        with st.spinner("Lettura sorgenti reali dalla property..."):
                            st.session_state[current_prop_key] = get_top_traffic_sources(sel_prop_id, st.session_state.credentials)
                    current_medium_key = f"mediums_{sel_prop_id}"
                    if current_medium_key not in st.session_state:
                        with st.spinner("Lettura medium reali dalla property..."):
                            st.session_state[current_medium_key] = get_top_traffic_mediums(sel_prop_id, st.session_state.credentials)
                    current_pairs_key = f"source_medium_pairs_{sel_prop_id}"
                    if current_pairs_key not in st.session_state:
                        with st.spinner("Lettura relazione source-medium dalla property..."):
                            st.session_state[current_pairs_key] = get_source_medium_pairs(sel_prop_id, st.session_state.credentials)
                    real_sources = st.session_state.get(current_prop_key, [])
                    real_mediums = st.session_state.get(current_medium_key, [])
                    pairs = st.session_state.get(current_pairs_key, [])
                    source_medium_map = {}
                    for src_raw, med_raw in pairs:
                        src_n = normalize_token(src_raw)
                        med_n = normalize_medium_token(med_raw)
                        if src_n and med_n:
                            source_medium_map.setdefault(src_n, set()).add(med_n)
                    if real_sources:
                        global SOURCE_OPTIONS
                        SOURCE_OPTIONS = sorted(list(set(get_source_options() + real_sources)))
                        preview = ", ".join(real_sources[:6])
                        st.markdown(f'<div class="tilda-note">Sorgenti recenti da GA4: {html_lib.escape(preview)}</div>', unsafe_allow_html=True)
                    if real_mediums:
                        medium_preview = ", ".join(real_mediums[:6])
                        st.markdown(f'<div class="tilda-note">Medium recenti da GA4: {html_lib.escape(medium_preview)}</div>', unsafe_allow_html=True)
            else:
                st.warning("Nessuna property disponibile nell'account selezionato.")
        else:
            st.warning("Nessun account GA4 trovato o accesso negato.")

        st.markdown('<div class="tilda-section">Your URL address</div>', unsafe_allow_html=True)
        url_col1, url_col2 = st.columns([0.16, 0.84], gap="small")
        with url_col1:
            url_scheme = st.selectbox(" ", ["https://", "http://"])
        with url_col2:
            url_domain = st.text_input(
                "URL di destinazione",
                placeholder="thismywebsite.com",
                help="Dove atterrerà l’utente quando clicca sulla CTA?"
            )
        url_domain = url_domain.strip()
        if url_domain.startswith("http://") or url_domain.startswith("https://"):
            destination_url = url_domain
        else:
            destination_url = f"{url_scheme}{url_domain}" if url_domain else ""
        domain_hint = prop_config.get("expected_domain", "")
        if not url_domain:
            st.markdown('<div class="msg-warning">⚠️ Inserisci un URL completo (es. https://example.com/pagina)</div>', unsafe_allow_html=True)
        elif not is_valid_url(destination_url):
            st.markdown('<div class="msg-error">❌ URL non valido. Usa formato corretto: https://dominio.tld/percorso</div>', unsafe_allow_html=True)
        elif domain_hint and domain_hint not in destination_url:
            st.markdown(f'<div class="msg-warning">⚠️ Dominio diverso da quello atteso: {html_lib.escape(domain_hint)}</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="msg-success">✅ URL valido</div>', unsafe_allow_html=True)

        st.markdown('<div class="tilda-section">Traffic source</div>', unsafe_allow_html=True)
        with st.expander("Golden Rules Naming Convention", expanded=False):
            st.markdown("""
            - Usa solo minuscole (GA4 è case-sensitive).
            - Evita spazi e caratteri speciali (`? % & $ !`); usa `-` o `_`.
            - Sii coerente nella struttura dei nomi.
            - Sii descrittivo ma conciso.
            - Preferisci i trattini (`-`) agli underscore (`_`) quando possibile.
            """)
        source_mode = st.radio(
            "Traffic source mode",
            ["Custom values", "Google Ads", "Social", "Email"],
            horizontal=True,
            label_visibility="collapsed"
        )

        source_default = ""
        medium_default = ""
        if source_mode == "Google Ads":
            source_default = "google"
            medium_default = "cpc"
        elif source_mode == "Social":
            source_default = "facebook"
            medium_default = "social_paid"
        elif source_mode == "Email":
            source_default = "newsletter"
            medium_default = "email"

        # In "Custom values" non mostriamo un preset extra:
        # l'utente compila direttamente utm_source/utm_medium nel blocco parametri.
        if source_mode == "Custom values":
            final_input_source = ""
        else:
            final_input_source = source_default

        st.markdown("")
        req_col, opt_col = st.columns(2, gap="large")
        with req_col:
            st.markdown('<div class="tilda-section">Required parameters</div>', unsafe_allow_html=True)
            st.caption("Campaign source")
            s1, s2 = st.columns([0.28, 0.72], gap="small")
            with s1:
                st.text_input(" ", value="utm_source", key="req_src_key", disabled=True)
            with s2:
                normalized_sources = sorted({normalize_token(s) for s in real_sources if normalize_token(s)})
                if not normalized_sources and not selected_prop_name:
                    normalized_sources = sorted({normalize_token(s) for s in get_source_options() if normalize_token(s) and "altro" not in s.lower()})
                source_options = filter_options_by_source_mode(normalized_sources, source_mode, "source")
                if not source_options:
                    source_options = [normalize_token(source_default)] if normalize_token(source_default) else []
                source_options = source_options + ["manuale"]
                source_default = normalize_token(final_input_source)
                source_index = source_options.index(source_default) if source_default in source_options else 0
                selected_source_value = st.selectbox(
                    "Source value",
                    source_options,
                    index=source_index,
                    key="req_src_val_select",
                    help="Su quale piattaforma o canale stai attivando questa campagna?"
                )
                if selected_source_value == "manuale":
                    utm_source = st.text_input(
                        "Manual source",
                        key="req_src_val_manual",
                        placeholder="google, facebook",
                        help="Su quale piattaforma o canale stai attivando questa campagna?"
                    )
                else:
                    utm_source = selected_source_value
                source_issues, source_suggest = validate_naming_rules(utm_source, prefer_hyphen=True)
                if source_issues:
                    st.markdown(
                        f'<div class="msg-error">❌ Source non conforme: {", ".join(source_issues)}. '
                        f'Suggerito: <b>{html_lib.escape(source_suggest)}</b></div>',
                        unsafe_allow_html=True
                    )
            st.caption("Campaign medium")
            m1, m2 = st.columns([0.28, 0.72], gap="small")
            with m1:
                st.text_input(" ", value="utm_medium", key="req_med_key", disabled=True)
            with m2:
                normalized_mediums = sorted({normalize_medium_token(m) for m in real_mediums if normalize_medium_token(m)})
                # Se c'e' property selezionata, medium dropdown basato su sessionMedium GA4.
                # Usiamo fallback tabellare solo quando GA4 non e' selezionato.
                if not normalized_mediums and not selected_prop_name:
                    fallback_mediums = []
                    for row in GUIDE_TABLE_DATA:
                        fallback_mediums.extend([normalize_medium_token(x) for x in str(row.get("utm_medium", "")).replace("|", ",").split(",") if normalize_medium_token(x)])
                    normalized_mediums = sorted(set(fallback_mediums))
                # Collega medium alla source selezionata usando la mappa GA4 source->medium.
                selected_source_normalized = normalize_token(utm_source) if 'utm_source' in locals() else ""
                mapped_mediums = sorted(source_medium_map.get(selected_source_normalized, set()))
                if mapped_mediums:
                    # Se abbiamo medium reali gia' mappati sulla source, NON rifiltriamo per canale:
                    # la relazione source->medium GA4 e' la fonte di verita'.
                    medium_options = mapped_mediums
                else:
                    # Fallback: nessuna coppia source-medium disponibile, applichiamo filtro di canale.
                    medium_options = filter_options_by_source_mode(normalized_mediums, source_mode, "medium")
                if not medium_options:
                    medium_options = [normalize_medium_token(medium_default)] if normalize_medium_token(medium_default) else []
                medium_options = medium_options + ["manuale"]
                default_medium_pick = normalize_medium_token(medium_default)
                medium_index = medium_options.index(default_medium_pick) if default_medium_pick in medium_options else 0
                selected_medium_value = st.selectbox(
                    "Medium value",
                    medium_options,
                    index=medium_index,
                    key="req_med_val_select",
                    help="Che tipo di campagna sarà? organic, social organico, social paid, email, ecc"
                )
                if selected_medium_value == "manuale":
                    utm_medium = st.text_input(
                        "Manual medium",
                        key="req_med_val_manual",
                        placeholder="cpc, email, banner, article",
                        help="Che tipo di campagna sarà? organic, social organico, social paid, email, ecc"
                    )
                else:
                    utm_medium = selected_medium_value
                medium_issues, medium_suggest = validate_naming_rules(utm_medium, prefer_hyphen=False)
                if medium_issues:
                    st.markdown(
                        f'<div class="msg-error">❌ Medium non conforme: {", ".join(medium_issues)}. '
                        f'Suggerito: <b>{html_lib.escape(medium_suggest)}</b></div>',
                        unsafe_allow_html=True
                    )
            st.caption("Campaign name")
            c1, c2 = st.columns([0.28, 0.72], gap="small")
            with c1:
                st.text_input(" ", value="utm_campaign", key="req_cmp_key", disabled=True)
            with c2:
                utm_campaign = st.text_input(
                    "Nome campagna",
                    key="req_cmp_val",
                    placeholder="promo, discount, sale",
                    help="Come chiameresti questa campagna internamente?",
                    autocomplete="new-password"
                )
                cmp_issues, cmp_suggest = validate_naming_rules(utm_campaign, prefer_hyphen=True)
                if cmp_issues:
                    st.markdown(
                        f'<div class="msg-error">❌ Nome campagna non conforme: {", ".join(cmp_issues)}. '
                        f'Suggerito: <b>{html_lib.escape(cmp_suggest)}</b></div>',
                        unsafe_allow_html=True
                    )
            type_col1, type_col2 = st.columns([0.28, 0.72], gap="small")
            with type_col1:
                st.text_input(" ", value="campaign_type", key="req_typ_key", disabled=True)
            with type_col2:
                campaign_type = st.text_input(
                    "Tipo campagna",
                    key="req_typ_val",
                    placeholder="always-on, promo, launch",
                    help="Tipologia della campagna (es. promo, launch, always-on)."
                )
                type_issues, type_suggest = validate_naming_rules(campaign_type, prefer_hyphen=True)
                if type_issues:
                    st.markdown(
                        f'<div class="msg-error">❌ Tipo campagna non conforme: {", ".join(type_issues)}. '
                        f'Suggerito: <b>{html_lib.escape(type_suggest)}</b></div>',
                        unsafe_allow_html=True
                    )
            meta_col1, meta_col2 = st.columns(2, gap="small")
            with meta_col1:
                campaign_start_date = st.date_input(
                    "Data di inizio campagna",
                    datetime.today(),
                    key="campaign_start_date",
                    format="DD/MM/YYYY",
                    help="Quando partirà la campagna?"
                )
            with meta_col2:
                campaign_language = st.text_input(
                    "Country/Lingua",
                    key="campaign_country_language",
                    placeholder="es. it, de, fr",
                    help="In che lingua è la comunicazione principale di questa campagna?"
                )
                lang_issues, lang_suggest = validate_naming_rules(campaign_language, prefer_hyphen=True)
                if lang_issues:
                    st.markdown(
                        f'<div class="msg-error">❌ Country/Lingua non conforme: {", ".join(lang_issues)}. '
                        f'Suggerito: <b>{html_lib.escape(lang_suggest)}</b></div>',
                        unsafe_allow_html=True
                    )

        with opt_col:
            st.markdown('<div class="tilda-section">Optional parameters</div>', unsafe_allow_html=True)
            st.caption("Campaign content")
            o1, o2 = st.columns([0.28, 0.72], gap="small")
            with o1:
                st.text_input(" ", value="utm_content", key="opt_cnt_key", disabled=True)
            with o2:
                utm_content = st.text_input(
                    "Content",
                    key="opt_cnt_val",
                    placeholder="cta, banner, image",
                    help="Dettaglia variante creativa, posizione o formato del contenuto."
                )
                cnt_issues, cnt_suggest = validate_naming_rules(utm_content, prefer_hyphen=True)
                if cnt_issues:
                    st.markdown(
                        f'<div class="msg-error">❌ Content non conforme: {", ".join(cnt_issues)}. '
                        f'Suggerito: <b>{html_lib.escape(cnt_suggest)}</b></div>',
                        unsafe_allow_html=True
                    )
            st.caption("Campaign term")
            t1, t2 = st.columns([0.28, 0.72], gap="small")
            with t1:
                st.text_input(" ", value="utm_term", key="opt_trm_key", disabled=True)
            with t2:
                utm_term = st.text_input(
                    "Term",
                    key="opt_trm_val",
                    placeholder="keyword, prospecting, retargeting",
                    help="Usato per keyword o segmenti specifici della campagna."
                )
                trm_issues, trm_suggest = validate_naming_rules(utm_term, prefer_hyphen=True)
                if trm_issues:
                    st.markdown(
                        f'<div class="msg-error">❌ Term non conforme: {", ".join(trm_issues)}. '
                        f'Suggerito: <b>{html_lib.escape(trm_suggest)}</b></div>',
                        unsafe_allow_html=True
                    )

        p_src = normalize_token(utm_source)
        p_med = normalize_medium_token(utm_medium)
        p_cmp_name = normalize_token(utm_campaign)
        p_cmp_type = normalize_token(campaign_type)
        p_cmp_lang = normalize_token(campaign_language)
        p_cmp_date = campaign_start_date.strftime("%d%m%Y")
        cmp_parts = [p for p in [p_cmp_lang, p_cmp_type, p_cmp_name, p_cmp_date] if p]
        p_cmp = "_".join(cmp_parts)
        p_cnt = normalize_token(utm_content)
        p_trm = normalize_token(utm_term)

        errors = []
        if not destination_url or not is_valid_url(destination_url):
            errors.append("URL")
        if not p_src:
            errors.append("utm_source")
        if not p_med:
            errors.append("utm_medium")
        if not p_cmp_name:
            errors.append("nome_campagna")
        if not p_cmp_type:
            errors.append("campaign_type")
        if not p_cmp_lang:
            errors.append("country_lingua")
        if source_issues:
            errors.append("source_naming")
        if medium_issues:
            errors.append("medium_naming")
        if cmp_issues:
            errors.append("campaign_name_naming")
        if type_issues:
            errors.append("campaign_type_naming")
        if lang_issues:
            errors.append("country_lingua_naming")
        if utm_content and cnt_issues:
            errors.append("content_naming")
        if utm_term and trm_issues:
            errors.append("term_naming")

        st.markdown('<div class="tilda-section">Result URL</div>', unsafe_allow_html=True)
        final_url = ""
        if errors:
            st.markdown(
                f'<div class="output-box-ready"><b>Compila i campi obbligatori.</b><br><small>Mancano: {", ".join(errors)}</small></div>',
                unsafe_allow_html=True
            )
        else:
            sep = "&" if "?" in destination_url else "?"
            final_url = f"{destination_url}{sep}utm_source={p_src}&utm_medium={p_med}&utm_campaign={p_cmp}"
            if p_cnt:
                final_url += f"&utm_content={p_cnt}"
            if p_trm:
                final_url += f"&utm_term={p_trm}"

            # Save candidate entry for history tab
            history_entry = {
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "user_email": st.session_state.get("user_email", ""),
                "property_id": sel_prop_id or "",
                "property_name": selected_prop_name or "",
                "campaign_name": utm_campaign,
                "live_date": campaign_start_date.strftime("%d/%m/%Y"),
                "utm_source": p_src,
                "utm_medium": p_med,
                "utm_campaign": p_cmp,
                "final_url": final_url,
                "expected_channel_group": infer_expected_channel_group(p_med),
            }
        result_btn_col, result_input_col = st.columns([0.12, 0.88], gap="small")
        with result_btn_col:
            copy_value = json.dumps(final_url if final_url else "")
            copy_disabled = "disabled" if not final_url else ""
            components.html(
                f"""
                <style>
                    html, body {{
                        margin: 0;
                        padding: 0;
                    }}
                    #copy-btn {{
                        width: 100%;
                        height: 40px;
                        border-radius: 8px;
                        border: 1px solid #c8d8e8;
                        background: #f7f9fc;
                        color: #1f2f3f;
                        font-weight: 600;
                        cursor: pointer;
                    }}
                    #copy-btn:disabled {{
                        opacity: 0.65;
                        cursor: not-allowed;
                    }}
                </style>
                <button id="copy-btn" {copy_disabled}
                    >
                    Copy
                </button>
                <script>
                    const btn = document.getElementById('copy-btn');
                    btn?.addEventListener('click', async () => {{
                        try {{
                            await navigator.clipboard.writeText({copy_value});
                            btn.innerText = 'Copied';
                            setTimeout(() => btn.innerText = 'Copy', 1200);
                        }} catch (e) {{
                            btn.innerText = 'Copy failed';
                            setTimeout(() => btn.innerText = 'Copy', 1200);
                        }}
                    }});
                </script>
                """,
                height=40,
            )
        with result_input_col:
            st.text_input(
                "Result",
                value=final_url,
                placeholder="You will see the result of your actions here...",
                label_visibility="collapsed"
            )
        if final_url:
            if st.button("Salva nello storico", key="save_history_btn", use_container_width=True):
                upsert_utm_history_entry(history_entry)
                st.success("Link salvato nello storico UTM.")

        with st.expander("📘 Tabella guida parametri UTM"):
            st.table(pd.DataFrame(GUIDE_TABLE_DATA))

    # ==============================================================================
    # TAB 2: UTM CHECKER (CORRETTO E PULITO)
    # ==============================================================================
    with tab_checker:
        st.markdown("### Check URL")
        st.markdown("Incolla un URL e controlla rapidamente stato HTTPS, struttura e parametri UTM.")
        
        check_url_input = st.text_input("Inserisci qui il tuo URL con UTM", placeholder="https://sito.it?utm_source=...")
        
        if st.button("Check URL", type="primary"):
            if not check_url_input:
                st.error("Inserisci un URL per procedere.")
            else:
                try:
                    parsed = urlparse(check_url_input)
                    params = parse_qs(parsed.query)
                    
                    # 1. URL CHECKS
                    st.markdown("### URL checks")

                    is_https = parsed.scheme == 'https'
                    length = len(check_url_input)
                    has_utm = any(k.startswith('utm_') for k in params.keys())

                    https_badge = '<span class="status-badge badge-ok">Valido</span>' if is_https else '<span class="status-badge badge-warn">Non sicuro</span>'
                    len_badge = '<span class="status-badge badge-ok">Valido</span>' if length < 2048 else '<span class="status-badge badge-warn">Lungo</span>'
                    utm_badge = '<span class="status-badge badge-ok">Presente</span>' if has_utm else '<span class="status-badge badge-bad">Assente</span>'

                    st.markdown(f"""
                    <div class="checks-grid">
                        <div class="checks-item">
                            <div class="checks-label">HTTPS</div>
                            {https_badge}
                        </div>
                        <div class="checks-item">
                            <div class="checks-label">Lunghezza URL ({length} caratteri)</div>
                            {len_badge}
                        </div>
                        <div class="checks-item">
                            <div class="checks-label">Parametri UTM</div>
                            {utm_badge}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                    # 2. UTM CHECKS
                    st.markdown("### UTM checks")

                    fields_to_check = [
                        ("UTM Source", "utm_source", True),
                        ("UTM Medium", "utm_medium", True),
                        ("UTM Campaign", "utm_campaign", True),
                        ("UTM Term", "utm_term", False),
                        ("UTM Content", "utm_content", False)
                    ]

                    html_output = '<div class="utm-compact-grid">'
                    for label, key, is_required in fields_to_check:
                        val_list = params.get(key, [])
                        val = val_list[0] if val_list else None

                        if val:
                            badge = '<span class="status-badge badge-ok">Valido</span>'
                            display_val = html_lib.escape(val)
                        else:
                            if is_required:
                                badge = '<span class="status-badge badge-bad">Mancante</span>'
                                display_val = '<span class="error-text">Parametro obbligatorio assente</span>'
                            else:
                                badge = '<span class="status-badge badge-opt">Opzionale</span>'
                                display_val = '<span style="color:#7a8896">Non valorizzato</span>'

                        html_output += (
                            '<div class="utm-param-item">'
                            f'<div class="utm-param-title">{label}</div>'
                            f'{badge}'
                            f'<div class="utm-param-value">{display_val}</div>'
                            '</div>'
                        )

                    html_output += "</div>"
                    st.markdown(html_output, unsafe_allow_html=True)

                except Exception as e:
                    st.error(f"Errore analisi URL: {e}")

    # ==============================================================================
    # TAB 3: UTM HISTORY & TRACKING
    # ==============================================================================
    with tab_history:
        st.markdown("### UTM History & Tracking")
        st.markdown("Storico dei link UTM creati, con verifica del corretto channel grouping in GA4.")

        history_items = load_utm_history()
        prop_lookup = build_property_name_lookup(st.session_state.get("ga4_accounts", []))
        user_email = st.session_state.get("user_email", "")
        if user_email:
            history_items = [x for x in history_items if x.get("user_email") == user_email]
        history_items = sorted(
            history_items,
            key=lambda x: (x.get("live_date", ""), x.get("campaign_name", "")),
            reverse=True
        )

        if not history_items:
            st.info("Nessun link storico disponibile. Genera un link e clicca 'Salva nello storico'.")
        else:
            base_rows = []
            for item in history_items:
                base_rows.append(
                    {
                        "Campagna": item.get("campaign_name", "-"),
                        "Periodo": item.get("live_date", "-"),
                        "UTM (source / medium / campaign)": f"{item.get('utm_source','-')} / {item.get('utm_medium','-')} / {item.get('utm_campaign','-')}",
                        "Canale atteso": item.get("expected_channel_group", "-"),
                        "Stato tracking": "Da verificare",
                    }
                )
            st.dataframe(pd.DataFrame(base_rows), use_container_width=True, hide_index=True)

            selected_campaign = st.selectbox(
                "Seleziona campagna da verificare",
                [f"{x.get('campaign_name','-')} ({x.get('live_date','-')})" for x in history_items],
            )
            selected_index = [f"{x.get('campaign_name','-')} ({x.get('live_date','-')})" for x in history_items].index(selected_campaign)
            selected_item = history_items[selected_index]
            grace_days = st.number_input("Giorni di grace period post-live", min_value=0, max_value=30, value=2, step=1)

            if st.button("Verifica tracking su GA4", key="check_tracking_history_btn", type="primary"):
                result = check_tracking_status_for_entry(selected_item, st.session_state.credentials, grace_days=int(grace_days))
                status_icon = {"OK": "✅", "WARNING": "⚠️", "ERROR": "❌", "PENDING": "⏳"}.get(result["status"], "ℹ️")

                st.markdown(
                    f"""
                    <div class="output-box-ready">
                        <b>{status_icon} Stato tracking: {result['status']}</b><br>
                        <small>{html_lib.escape(result['message'])}</small>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                st.write("Dettaglio verifica:")
                detail_row = {
                    "Campagna": selected_item.get("campaign_name"),
                    "Periodo": selected_item.get("live_date"),
                    "GA4 Property Name": (
                        selected_item.get("property_name")
                        or prop_lookup.get(str(selected_item.get("property_id", "")).replace("properties/", ""))
                        or prop_lookup.get(str(selected_item.get("property_id", "")))
                        or "-"
                    ),
                    "GA4 Property ID": selected_item.get("property_id", "-"),
                    "UTM Source": selected_item.get("utm_source"),
                    "UTM Medium": selected_item.get("utm_medium"),
                    "UTM Campaign": selected_item.get("utm_campaign"),
                    "Sessions osservate": result.get("sessions", 0),
                    "Canale atteso": selected_item.get("expected_channel_group", "-"),
                    "Canale osservato": result.get("observed", "-"),
                    "Stato tracking": result.get("status"),
                }
                st.table(pd.DataFrame([detail_row]))

    # --- RENDER GLOBALLY (FLOATING) ---
    render_chatbot_interface(
        st.session_state.credentials,
        get_persistent_api_key,
        save_chatbot_url_to_history
    )


# --- MAIN APP FLOW ---
if __name__ == "__main__":
    if "credentials" not in st.session_state:
        st.session_state.credentials = None

    # Scopes setup for profile info
    if 'https://www.googleapis.com/auth/userinfo.profile' not in SCOPES:
        SCOPES.append('https://www.googleapis.com/auth/userinfo.profile')
    if 'https://www.googleapis.com/auth/userinfo.email' not in SCOPES:
        SCOPES.append('https://www.googleapis.com/auth/userinfo.email')

    # Auto-login check
    base_path = os.path.dirname(os.path.abspath(__file__))
    token_path = os.path.join(base_path, 'token.json')
    
    if st.session_state.credentials is None and os.path.exists(token_path):
         try:
             creds = Credentials.from_authorized_user_file(token_path, SCOPES)
             if creds and creds.valid:
                  st.session_state.credentials = creds
             elif creds and creds.expired and creds.refresh_token:
                  creds.refresh(Request())
                  st.session_state.credentials = creds
         except:
             pass

    # Fallback to web auth if token.json is not present (or we are in Cloud)
    if not st.session_state.credentials:
        query_params = st.query_params
        if "code" in query_params:
            auth_code = query_params["code"]
            flow = get_oauth_flow()
            if flow:
                try:
                    # Clear code verifier expectation because we bypassed it on generation
                    flow.code_verifier = None
                    flow.fetch_token(code=auth_code)
                    creds = flow.credentials
                    st.session_state.credentials = creds
                    
                    # Store as primitive dict to be completely safe with st.session_state
                    st.session_state.google_credentials = {
                        'token': creds.token,
                        'refresh_token': creds.refresh_token,
                        'token_uri': creds.token_uri,
                        'client_id': creds.client_id,
                        'client_secret': creds.client_secret,
                        'scopes': creds.scopes
                    }
                    
                    # Clean up URL params so we don't re-trigger the auth flow
                    st.query_params.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Errore durante l'autenticazione: {e}")
            else:
                st.error("Configurazione Flow mancante durante la validazione del codice.")

    # Restoring from session state primitive dict if page reloads
    if not st.session_state.credentials and "google_credentials" in st.session_state:
        g_creds = st.session_state.google_credentials
        st.session_state.credentials = Credentials(
            token=g_creds.get('token'),
            refresh_token=g_creds.get('refresh_token'),
            token_uri=g_creds.get('token_uri'),
            client_id=g_creds.get('client_id'),
            client_secret=g_creds.get('client_secret'),
            scopes=g_creds.get('scopes')
        )

    # Routing
    if st.session_state.credentials:
        show_dashboard()
    else:
        show_login_page()
