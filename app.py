import streamlit as st
import pandas as pd
import os
import json
from datetime import datetime
from slugify import slugify
from urllib.parse import urlparse, parse_qs

import re
import html as html_lib  # per escapare valori UTM nell'HTML

# Google Auth & Analytics import os
import google.auth
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.analytics.admin import AnalyticsAdminServiceClient
from google.analytics.data import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import RunReportRequest, DateRange, Metric, Dimension

import google.generativeai as genai
from googleapi import get_user_email, get_persistent_api_key, save_persistent_api_key
import ga4_mcp_tools # Import tools module
from functools import partial

# Import new Chatbot UI
from chatbot_ui import render_chatbot_interface

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Universal UTM Governance", layout="wide")

# --- CSS (STILE CLEAN + CHECKER CORRETTO) ---
st.markdown("""
<style>
    /* 1. Header Sezioni */
    .section-header {
        font-size: 12px; font-weight: 700; color: #888; margin-top: 25px; margin-bottom: 10px;
        text-transform: uppercase; letter-spacing: 1px; font-family: sans-serif;
    }
    
    /* 2. Messaggi Validazione */
    .msg-error { color: #d93025; font-size: 13px; margin-top: -5px; margin-bottom: 5px; display: flex; align-items: center; gap: 5px; }
    .msg-warning { color: #e37400; font-size: 13px; margin-top: -5px; margin-bottom: 5px; display: flex; align-items: center; gap: 5px; }
    .msg-success { color: #188038; font-size: 13px; margin-top: -5px; margin-bottom: 5px; display: flex; align-items: center; gap: 5px; font-weight: 500; }
    
    /* 3. Output Box Builder */
    .output-box-ready { background-color: #e8f0fe; color: #174ea6; padding: 15px; border-radius: 8px; border: 1px solid #d2e3fc; }
    .output-box-success { background-color: #e6f4ea; color: #137333; padding: 15px; border-radius: 8px; border: 1px solid #ceead6; }
    
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

</style>
""", unsafe_allow_html=True)

# --- GOOGLE AUTH FUNCTIONS ---
SCOPES = [
    'https://www.googleapis.com/auth/analytics.readonly',
    'https://www.googleapis.com/auth/analytics.edit',
    'https://www.googleapis.com/auth/userinfo.email',
    'openid'
]

def do_oauth_flow():
    """Effettua il flow di autenticazione Google OAuth 2.0 Locale"""
    creds = None
    
    # Percorsi assoluti
    base_path = os.path.dirname(os.path.abspath(__file__))
    token_path = os.path.join(base_path, 'token.json')
    secrets_path = os.path.join(base_path, 'client_secrets.json')
    
    # Token.json memorizza i token di accesso e refresh utente
    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        except Exception:
            # Token malformato o scaduto: eliminalo e riparte dall'OAuth
            os.remove(token_path)
            creds = None
    
    # Se non ci sono credenziali valide, fai il login
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                os.remove(token_path)
                return do_oauth_flow()
        else:
            if not os.path.exists(secrets_path):
                st.error(f"File '{secrets_path}' non trovato! Scaricalo da Google Cloud Console.")
                return None
                
            flow = InstalledAppFlow.from_client_secrets_file(
                secrets_path, SCOPES)
            # Usa una porta fissa (8080) per evitare mismatch con le URI autorizzate in Google Cloud
            try:
                creds = flow.run_local_server(
                    port=8080,
                    access_type='offline',
                    prompt='consent'  # forza Google a restituire sempre il refresh_token
                )
            except OSError as e:
                if "Address already in use" in str(e) or "[WinError 10048]" in str(e):
                    st.error("❌ Errore: La porta 8080 è occupata. Probabilmente un'altra istanza di login è rimasta appesa. Riprova tra qualche secondo o chiudi i processi python.exe dal Task Manager.")
                    return None
                else:
                    raise e
        
        # Salva le credenziali per il prossimo avvio
        with open(token_path, 'w') as token:
            token.write(creds.to_json())
            
    return creds

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

def is_valid_url(url):
    regex = re.compile(r'^https?://(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|localhost|\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?::\d+)?(?:/?|[/?]\S+)$', re.IGNORECASE)
    return re.match(regex, url) is not None

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
        
        if st.button("🔐 Login con Google", use_container_width=True, type="primary"):
            creds = do_oauth_flow()
            if creds:
                st.session_state.credentials = creds
                st.rerun()

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
    c_head_1, c_head_2, c_head_3 = st.columns([2.5, 0.5, 1])
    with c_head_1:
        st.title("🛡️ Universal UTM Governance")
    with c_head_2:
        # Settings button
        if st.button("⚙️", key="settings_btn", help="Impostazioni"):
            st.session_state.show_settings = not st.session_state.get("show_settings", False)
    with c_head_3:
        if st.button("Logout", key="logout_btn"):
            if "credentials" in st.session_state:
                del st.session_state.credentials
            if "user_email" in st.session_state:
                del st.session_state.user_email
            if "gemini_api_key" in st.session_state:
                del st.session_state.gemini_api_key
            if os.path.exists("token.json"):
                os.remove("token.json")
            st.rerun()

    # --- SETTINGS MODAL ---
    if st.session_state.get("show_settings", False):
        with st.expander("⚙️ Impostazioni", expanded=True):
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

    st.markdown("""
    **Guida passo a passo nella generazione di link completi di parametri UTM.**  
    Usa il **Builder** per creare nuovi link standardizzati o il **Checker** per analizzare link esistenti.
    """)
    st.write("---")

    # --- TABS DI NAVIGAZIONE ---
    tab_builder, tab_checker = st.tabs(["🛠️ UTM Generator", "🔍 UTM Checker"])

    # --- SESSION STATE PER CHAT ---
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # ==============================================================================
    # TAB 1: UTM GENERATOR (BUILDER)
    # ==============================================================================
    with tab_builder:
        col_left, col_right = st.columns([0.5, 0.5], gap="large")

        with col_left:
            # 1. SETUP & AUTH INFO
            st.markdown('<div class="section-header">SETUP</div>', unsafe_allow_html=True)
            
            selected_prop_name = None
            prop_channels = ["Paid Search", "Paid Social", "Display", "Email", "Organic Social", "Affiliate", "Video", "Altro"] # Default fallback
            prop_config = {"default_country": "it", "expected_domain": ""}

            if "ga4_accounts" not in st.session_state:
                with st.spinner("Caricamento Account GA4..."):
                    st.session_state.ga4_accounts = get_ga4_accounts_structure(st.session_state.credentials)
            
            accounts_structure = st.session_state.ga4_accounts
            
            if accounts_structure:
                # 1. Seleziona Account
                account_names = [a["display_name"] for a in accounts_structure]
                selected_account_name = st.selectbox("Cliente (Account)", account_names)
                
                # Trova l'account selezionato
                selected_account = next((a for a in accounts_structure if a["display_name"] == selected_account_name), None)
                
                if selected_account and selected_account["properties"]:
                    # 2. Seleziona Property dell'account
                    prop_map = {p["display_name"]: p["property_id"] for p in selected_account["properties"]}
                    prop_names = list(prop_map.keys())
                    selected_prop_name = st.selectbox("Property GA4", prop_names)
                    
                    if selected_prop_name:
                         sel_prop_id = prop_map[selected_prop_name]
                         
                         # --- FETCH SORGENTI REALI ---
                         current_prop_key = f"sources_{sel_prop_id}"
                         if current_prop_key not in st.session_state:
                            with st.spinner("Analisi sorgenti in uso..."):
                               real_sources = get_top_traffic_sources(sel_prop_id, st.session_state.credentials)
                               st.session_state[current_prop_key] = real_sources
                        
                         real_sources = st.session_state.get(current_prop_key, [])
                         if real_sources:
                            global SOURCE_OPTIONS
                            SOURCE_OPTIONS = sorted(list(set(get_source_options() + real_sources)))
                else:
                    st.warning("Nessuna property in questo account.")
                    sel_prop_id = None
            else:
                st.warning("Nessun account GA4 trovato o accesso negato.")

            # 2. CANALI
            st.markdown('<div class="section-header">CANALI</div>', unsafe_allow_html=True)
            
            selected_source_option = st.selectbox("Piattaforma / Source *", SOURCE_OPTIONS, help="Su quale piattaforma o canale stai attivando questa campagna?")
            final_input_source = ""
            if selected_source_option == "Altro (Inserisci manuale)":
                final_input_source = st.text_input("Inserisci Source Manuale", placeholder="es. nuova-piattaforma")
            else:
                final_input_source = selected_source_option
            
            if final_input_source:
                src_clean = normalize_token(final_input_source)
                if final_input_source != src_clean:
                    st.markdown(f'<div class="msg-warning">⚠️ Consigliato: {src_clean}</div>', unsafe_allow_html=True)
                else:
                    st.markdown('<div class="msg-success">✅ OK</div>', unsafe_allow_html=True)

            available_channels = get_compatible_channels(final_input_source, prop_channels)
            sel_channel = st.selectbox("Channel Grouping", available_channels, help="In quale channel grouping vuoi che venga raccolto il traffico?")
            
            real_opts = [c for c in available_channels if c]
            if len(real_opts) > 1 and not sel_channel:
                st.markdown(f'<div class="msg-error">❌ Seleziona un canale (Sorgente ambigua)</div>', unsafe_allow_html=True)
            elif sel_channel:
                st.markdown('<div class="msg-success">✅ OK</div>', unsafe_allow_html=True)

            # 3. DESTINAZIONE
            st.markdown('<div class="section-header">DESTINAZIONE</div>', unsafe_allow_html=True)
            
            domain_hint = prop_config.get('expected_domain', '')
            destination_url = st.text_input("URL Atterraggio *", value="https://", help="Dove atterrerà l’utente quando clicca sulla CTA?")
            
            if destination_url == "https://" or not destination_url:
                pass
            elif not is_valid_url(destination_url):
                st.markdown('<div class="msg-error">❌ URL non valido (es. https://sito.it)</div>', unsafe_allow_html=True)
            elif domain_hint and domain_hint not in destination_url:
                st.markdown(f'<div class="msg-warning">⚠️ Dominio diverso da {domain_hint}</div>', unsafe_allow_html=True)
            else:
                st.markdown('<div class="msg-success">✅ URL valido</div>', unsafe_allow_html=True)

            # 4. NAMING CAMPAGNA
            st.markdown('<div class="section-header">NAMING CAMPAGNA</div>', unsafe_allow_html=True)
            st.caption("Pattern: `Country_Type_Name_Date_CTA`")

            inp_country = st.text_input("Country *", value=prop_config["default_country"], help="In che lingua è la comunicazione?")
            if inp_country: st.markdown('<div class="msg-success">✅ OK</div>', unsafe_allow_html=True)
            
            c1, c2 = st.columns(2)
            with c1:
                inp_type = st.text_input("Type", placeholder="es. promo", help="Che tipo di campagna è?")
                if inp_type: st.markdown('<div class="msg-success">✅ OK</div>', unsafe_allow_html=True)
            with c2:
                inp_name = st.text_input("Nome Campagna *", placeholder="es. saldi", help="Come chiameresti questa campagna?")
                if inp_name:
                    nm_norm = normalize_token(inp_name)
                    if inp_name != nm_norm:
                        st.markdown(f'<div class="msg-warning">⚠️ Usa: {nm_norm}</div>', unsafe_allow_html=True)
                    else:
                        st.markdown('<div class="msg-success">✅ OK</div>', unsafe_allow_html=True)

            c3, c4 = st.columns(2)
            with c3:
                inp_date = st.date_input("Start Date", datetime.today(), help="Quando partirà la campagna?")
                st.markdown('<div class="msg-success">✅ OK</div>', unsafe_allow_html=True)
            with c4:
                inp_cta = st.text_input("CTA / Content", placeholder="es. banner", help="Qual è la CTA?")
                if inp_cta: st.markdown('<div class="msg-success">✅ OK</div>', unsafe_allow_html=True)


        # COLONNA DESTRA (OUTPUT)
        with col_right:
            st.markdown("### 🚀 Link Finale")
            
            date_str = inp_date.strftime("%Y%m%d")
            p_cnt = normalize_token(inp_country)
            p_typ = normalize_token(inp_type)
            p_nam = normalize_token(inp_name)
            p_cta = normalize_token(inp_cta)
            p_src = normalize_token(final_input_source)
            p_med = normalize_token(sel_channel)

            parts = []
            if p_cnt: parts.append(p_cnt)
            if p_typ: parts.append(p_typ)
            if p_nam: parts.append(p_nam)
            parts.append(date_str)
            if p_cta: parts.append(p_cta)
            
            final_campaign = "_".join(parts)

            errors = []
            if not is_valid_url(destination_url): errors.append("URL")
            if not p_src: errors.append("Source")
            if len(real_opts) > 1 and not sel_channel: errors.append("Canale")
            if not p_cnt: errors.append("Country")
            if not p_nam: errors.append("Name")

            if errors:
                st.markdown(f"""
                <div class="output-box-ready">
                    👉 <b>Compila i campi obbligatori a sinistra per generare il link.</b><br>
                    <small>Mancano: {", ".join(errors)}</small>
                </div>
                """, unsafe_allow_html=True)
            else:
                sep = "&" if "?" in destination_url else "?"
                final_url = f"{destination_url}{sep}utm_source={p_src}&utm_medium={p_med}&utm_campaign={final_campaign}"
                if p_cta: final_url += f"&utm_content={p_cta}"
                
                st.markdown(f"""
                <div class="output-box-success">
                    ✅ <b>Link pronto per l'uso</b>
                </div>
                """, unsafe_allow_html=True)
                
                st.code(final_url, language="text")
                
                st.write("Parametri Tecnici:")
                st.json({
                    "source": p_src,
                    "medium": p_med,
                    "campaign": final_campaign,
                    "content": p_cta
                })


            st.write("")
            st.write("")
            with st.expander("📘 Guida ai Canali"):
                st.table(pd.DataFrame(GUIDE_TABLE_DATA))




    # ==============================================================================
    # TAB 2: UTM CHECKER (CORRETTO E PULITO)
    # ==============================================================================
    with tab_checker:
        st.markdown("### UTM Checker Tool")
        st.markdown("Usa questo strumento per verificare se i parametri UTM del tuo link sono impostati correttamente.")
        
        check_url_input = st.text_input("Inserisci qui il tuo URL con UTM", placeholder="https://sito.it?utm_source=...")
        
        if st.button("Analizza URL", type="primary"):
            if not check_url_input:
                st.error("Inserisci un URL per procedere.")
            else:
                try:
                    parsed = urlparse(check_url_input)
                    params = parse_qs(parsed.query)
                    
                    # 1. URL CHECKS
                    st.markdown("### URL checks")
                    
                    is_https = parsed.scheme == 'https'
                    icon_https = "✅" if is_https else "⚠️"
                    val_https = "Yes" if is_https else "No (Not Secure)"
                    
                    length = len(check_url_input)
                    icon_len = "✅" if length < 2048 else "⚠️"
                    
                    has_utm = any(k.startswith('utm_') for k in params.keys())
                    icon_utm = "✅" if has_utm else "❌"
                    val_utm = "Yes" if has_utm else "No"

                    st.markdown(f"""
                    <div class="utm-check-card">
                        <div class="utm-row">
                            <div class="utm-label-col" style="font-weight:bold; color:#555;">HTTPS</div>
                            <div class="utm-value-col">{icon_https} {val_https}</div>
                        </div>
                        <div class="utm-row">
                            <div class="utm-label-col" style="font-weight:bold; color:#555;">URL length</div>
                            <div class="utm-value-col">{icon_len} {length} chars</div>
                        </div>
                        <div class="utm-row">
                            <div class="utm-label-col" style="font-weight:bold; color:#555;">Contains UTM</div>
                            <div class="utm-value-col">{icon_utm} {val_utm}</div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # 2. UTM CHECKS (COSTRUZIONE STRINGA HTML UNICA)
                    st.markdown("### UTM checks")
                    
                    # Definizione Campi e Obbligatorietà
                    fields_to_check = [
                        ("UTM Source", "utm_source", "tag-blue", True),   # True = Obbligatorio
                        ("UTM Medium", "utm_medium", "tag-blue", True),
                        ("UTM Campaign", "utm_campaign", "tag-blue", True),
                        ("UTM Term", "utm_term", "tag-gray", False),
                        ("UTM Content", "utm_content", "tag-gray", False)
                    ]
                    
                    # Inizializza la stringa HTML
                    html_output = '<div class="utm-check-card">'
                    
                    for label, key, tag_class, is_required in fields_to_check:
                        val_list = params.get(key, [])
                        val = val_list[0] if val_list else None

                        if val:
                            # Valore presente (VERDE)
                            display_val = f'{val} <span class="check-icon">✔</span>'
                        else:
                            if is_required:
                                display_val = '<span class="error-text">Mancante</span> <span class="error-icon">✖</span>'
                            else:
                                display_val = '<span style="color:#ccc">-</span>'

                        # Riga HTML: NESSUNA indentazione per evitare che Markdown la tratti come code block
                        html_output += (
                            '<div class="utm-row">'
                            f'<div class="utm-label-col"><span class="utm-tag {tag_class}">{label}:</span></div>'
                            f'<div class="utm-value-col">{display_val}</div>'
                            '</div>'
                        )

                    html_output += "</div>"

                    # Stampa tutto l'HTML in una volta sola
                    st.markdown(html_output, unsafe_allow_html=True)

                except Exception as e:
                    st.error(f"Errore analisi URL: {e}")

    # --- RENDER GLOBALLY (FLOATING) ---
    render_chatbot_interface(st.session_state.credentials, get_persistent_api_key)


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

    # Routing
    if st.session_state.credentials:
        show_dashboard()
    else:
        show_login_page()
