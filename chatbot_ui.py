import streamlit as st
import os
import base64
import re
import json
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

import google.generativeai as genai
import ga4_mcp_tools  # Importa il modulo con i tool GA4


# -------------------------
# Utility (UI / cleaning)
# -------------------------
def get_base64_image(image_path: str) -> Optional[str]:
    """Helper per convertire immagini in base64 (se necessario per UI future)"""
    if os.path.exists(image_path):
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode()
    return None


def _dedupe_repetitions(text: str) -> str:
    """
    Riduce ripetizioni accidentali tipiche dei LLM:
    - "awarenessawareness" -> "awareness"
    - "saldi invernali saldi invernali" -> "saldi invernali"
    - "IT IT" -> "IT"
    """
    if not text:
        return text

    # 1) Ripetizioni concatenate senza spazi: "abcabc" -> "abc" (min 3 char per evitare falsi positivi)
    text = re.sub(r"\b([A-Za-zÀ-ÖØ-öø-ÿ0-9_]{3,})\1\b", r"\1", text)

    # 2) Ripetizione di una parola: "IT IT" -> "IT"
    text = re.sub(r"\b(\w+)(\s+\1\b)+", r"\1", text, flags=re.IGNORECASE)

    # 3) Ripetizione di sequenze di 2-4 parole: "saldi invernali saldi invernali" -> "saldi invernali"
    text = re.sub(
        r"\b((?:\w+\s+){1,3}\w+)\s+\1\b",
        r"\1",
        text,
        flags=re.IGNORECASE,
    )

    return text


def _extract_first_url(text: str) -> Optional[str]:
    """
    Estrae il primo URL presente in una stringa.
    Supporta URL con o senza schema.
    """
    if not text:
        return None

    # 1) URL completi
    m = re.search(r"(https?://[^\s]+)", text)
    if m:
        return m.group(1).strip()

    # 2) URL tipo www.sito.it/...
    m = re.search(r"\b(www\.[^\s]+)\b", text)
    if m:
        return m.group(1).strip()

    # 3) URL tipo dominio.tld/...
    m = re.search(r"\b([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})(/[^\s]*)?\b", text)
    if m:
        return (m.group(1) + (m.group(2) or "")).strip()

    return None


def _normalize_destination_url(raw_url: str) -> str:
    """
    Normalizza l'URL di destinazione allo standard richiesto:
    - Deve iniziare con https://www.
    - Evita duplicazioni (no sito.itsito.it)
    """
    raw_url = (raw_url or "").strip()

    # se manca schema
    if raw_url.startswith("www."):
        raw_url = "https://" + raw_url
    elif not raw_url.startswith("http://") and not raw_url.startswith("https://"):
        raw_url = "https://" + raw_url

    parsed = urlparse(raw_url)

    host = parsed.netloc or ""
    path = parsed.path or ""

    # Se netloc vuoto (caso raro: urlparse su stringhe strane), tenta fix
    if not host and parsed.path:
        # esempio: "chicco.it/abc" -> path contiene tutto
        tmp = parsed.path.split("/", 1)
        host = tmp[0]
        path = "/" + tmp[1] if len(tmp) > 1 else ""

    # aggiungi www se non presente
    if host and not host.startswith("www."):
        host = "www." + host

    # ricostruisci
    normalized = urlunparse(
        (
            "https",               # scheme
            host,                  # netloc
            path,                  # path
            "",                    # params
            parsed.query or "",    # query
            parsed.fragment or "", # fragment
        )
    )

    # evita duplicazioni dominio accidentali tipo "sito.itsito.it"
    # (semplice guard-rail: se host contiene due volte lo stesso dominio base, prova a ridurre)
    # Non perfetto, ma evita gli errori più comuni.
    if host.count(".") >= 2:
        parts = host.split(".")
        # www + base + tld: ok. Se molto lungo, non tocchiamo.
        # In ogni caso, la duplicazione tipica era "sito.itsito.it": la riduzione automatica è rischiosa.
        pass

    return normalized


def _sanitize_utm_value(value: str) -> str:
    """
    Normalizza i valori UTM:
    - lowercase
    - spazi -> underscore
    - rimuove caratteri speciali (mantiene a-z0-9_-)
    """
    if value is None:
        return ""
    v = str(value).strip().lower()
    v = v.replace(" ", "_")
    v = re.sub(r"[^\w-]", "_", v)  # \w include underscore e numeri/lettere
    v = re.sub(r"_+", "_", v).strip("_")
    return v


def _try_fix_date_to_ddmmyyyy(date_str: str) -> Optional[str]:
    """
    Accetta input comuni e restituisce data in formato GG-MM-AAAA.
    Esempi supportati:
    - 2026-02-10 -> 10-02-2026
    - 10.02.26 -> 10-02-2026
    - 10/02/2026 -> 10-02-2026
    """
    if not date_str:
        return None

    s = date_str.strip()

    # YYYY-MM-DD
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        yyyy, mm, dd = m.group(1), m.group(2), m.group(3)
        return f"{dd}-{mm}-{yyyy}"

    # DD.MM.YY or DD.MM.YYYY
    m = re.match(r"^(\d{2})\.(\d{2})\.(\d{2,4})$", s)
    if m:
        dd, mm, yy = m.group(1), m.group(2), m.group(3)
        if len(yy) == 2:
            yy = "20" + yy
        return f"{dd}-{mm}-{yy}"

    # DD/MM/YYYY
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", s)
    if m:
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        return f"{dd}-{mm}-{yyyy}"

    return None


def _rebuild_url_with_encoded_query(url: str) -> str:
    """
    Forza un encoding corretto della query string (evita spazi e caratteri speciali non encodati).
    Mantiene scheme/netloc/path; ri-encoda query.
    """
    try:
        p = urlparse(url)
        qs = parse_qsl(p.query, keep_blank_values=True)
        encoded = urlencode(qs, doseq=True, safe="")  # encoda tutto ciò che serve
        return urlunparse((p.scheme, p.netloc, p.path, p.params, encoded, p.fragment))
    except Exception:
        return url


def _extract_json_block_if_any(text: str) -> Optional[Dict[str, Any]]:
    """
    Se il modello stampa un JSON tra { ... } con chiavi utm_*, prova a parsarlo.
    """
    if not text or "utm_" not in text:
        return None
    # trova il primo blocco {...} “ampio”
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        return None
    candidate = m.group(0)
    try:
        data = json.loads(candidate)
        if isinstance(data, dict) and any(k.startswith("utm_") for k in data.keys()):
            return data
    except Exception:
        return None
    return None


def clean_bot_response(text: str) -> str:
    """
    Pulisce la risposta del bot:
    - rimuove artefatti HTML / backticks
    - riduce ripetizioni
    - se il bot stampa JSON + link: mantiene SOLO il link finale (come richiesto)
    - forza encoding corretto del link se presente
    """
    if not text:
        return ""

    # rimuove HTML che può allucinare
    text = text.replace("</div>", "").replace("<div>", "")
    text = text.replace("<br>", "\n")

    # rimuove backticks
    text = text.replace("```json", "").replace("```", "")

    # dedupe
    text = _dedupe_repetitions(text).strip()

    # Se contiene un JSON con utm_*, estrai link e mostra solo link + istruzione
    parsed_json = _extract_json_block_if_any(text)
    if parsed_json:
        # prova a ricostruire link da json
        base_url = parsed_json.get("url") or parsed_json.get("URL") or parsed_json.get("destination_url") or ""
        base_url = _normalize_destination_url(str(base_url)) if base_url else ""

        utm_pairs = []
        for k in ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"]:
            v = parsed_json.get(k)
            if v is None or v == "" or str(v).lower() == "null":
                continue
            utm_pairs.append((k, str(v)))

        if base_url:
            p = urlparse(base_url)
            original_qs = parse_qsl(p.query, keep_blank_values=True)
            merged = original_qs + utm_pairs
            encoded = urlencode(merged, doseq=True, safe="")
            final_url = urlunparse((p.scheme, p.netloc, p.path, p.params, encoded, p.fragment))
            final_url = _rebuild_url_with_encoded_query(final_url)
            return "Copia e incolla questo link completo:\n" + final_url

    # Se il testo include un URL, prova a “ripulire” e re-encodare solo quello
    url_in_text = _extract_first_url(text)
    if url_in_text:
        norm = _normalize_destination_url(url_in_text)
        fixed = _rebuild_url_with_encoded_query(norm)

        # Se il bot ha scritto testo + url, mantieni solo l’istruzione + url
        # (per rispettare la richiesta “output solo link”)
        if "utm_" in fixed:
            return "Copia e incolla questo link completo:\n" + fixed

    return text


# -------------------------
# Gemini wrapper
# -------------------------
def get_gemini_response_safe(
    user_input: str,
    history: List[Dict[str, Any]],
    tools: List[Any],
    system_instruction: str,
    api_key: str
) -> Tuple[str, str]:
    """
    Tenta di ottenere una risposta provando una lista estesa di modelli.
    Ritorna: (testo, nome_modello)
    """
    models_to_try = [
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-1.5-flash-001",
        "gemini-1.5-pro",
        "gemini-1.0-pro",
        "gemini-pro",
    ]

    last_error = None

    for model_name in models_to_try:
        try:
            model = genai.GenerativeModel(
                model_name,
                tools=tools,
                system_instruction=system_instruction
            )

            chat = model.start_chat(
                history=history,
                enable_automatic_function_calling=True
            )

            response = chat.send_message(user_input)
            return response.text, model_name

        except Exception as e:
            last_error = e
            error_str = str(e).lower()

            if "404" in error_str or "not found" in error_str or "not supported" in error_str:
                continue
            if "api key" in error_str or "permission" in error_str or "403" in error_str:
                raise e
            continue

    raise Exception(
        "❌ Impossibile trovare un modello Gemini attivo per questa API Key.\n"
        f"Ultimo errore: {str(last_error)}\n"
    )


# -------------------------
# Main UI
# -------------------------
def render_chatbot_interface(creds, api_key_func=None) -> None:
    """
    Renderizza il widget Chatbot Inline.
    """
    # Stato
    if "chat_visible" not in st.session_state:
        st.session_state.chat_visible = False
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # CSS
    st.markdown(
        """
        <style>
            .inline-chat-container {
                background: white;
                border-radius: 12px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.1);
                border: 1px solid #e5e7eb;
                overflow: hidden;
                font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                height: 100%;
                display: flex;
                flex-direction: column;
            }
            .inline-chat-header {
                background: #2563eb;
                color: white;
                padding: 14px 18px;
                display: flex;
                justify-content: space-between;
                align-items: center;
                font-weight: 600;
                font-size: 16px;
            }
            .inline-chat-header-title { display: flex; align-items: center; gap: 8px; }
            .inline-message-bubble { display: flex; margin-bottom: 12px; }
            .inline-bubble-content {
                padding: 10px 14px;
                border-radius: 12px;
                font-size: 14px;
                line-height: 1.5;
                max-width: 85%;
                white-space: pre-wrap;
                word-break: break-word;
            }
            .inline-user-bubble {
                background: #2563eb;
                color: white;
                border-bottom-right-radius: 3px;
                margin-left: auto;
            }
            .inline-model-bubble {
                background: #f3f4f6;
                color: #374151;
                border: 1px solid #e5e7eb;
                border-bottom-left-radius: 3px;
                margin-right: auto;
            }
            .inline-welcome-message {
                background: #eff6ff;
                color: #1e40af;
                padding: 16px;
                border-radius: 8px;
                text-align: center;
                margin: 20px;
                border: 1px solid #dbeafe;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Bottone apertura
    if not st.session_state.chat_visible:
        if st.button("🤖 Apri WR Assistant", key="open_chat_btn", use_container_width=True):
            st.session_state.chat_visible = True
            st.rerun()
        return

    # Container
    st.markdown('<div class="inline-chat-container">', unsafe_allow_html=True)

    # Header
    col_header, col_close = st.columns([0.85, 0.15])
    with col_header:
        st.markdown(
            """
            <div class="inline-chat-header">
                <div class="inline-chat-header-title">
                    <span>🤖 WR Assistant</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col_close:
        if st.button("✕", key="close_chat_btn", help="Chiudi chat"):
            st.session_state.chat_visible = False
            st.rerun()

    # Messaggi
    messages_container = st.container(height=450)
    with messages_container:
        if not st.session_state.messages:
            st.markdown(
                """
                <div class="inline-welcome-message">
                    <b>WR Assistant</b><br><br>
                    Posso aiutarti a generare link UTM corretti seguendo le best practice aziendali.<br>
                    Scrivi <i>"crea un nuovo link"</i> o incolla un URL per iniziare.
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            for msg in st.session_state.messages:
                if msg["role"] == "user":
                    st.markdown(
                        f"""
                        <div class="inline-message-bubble">
                            <div class="inline-bubble-content inline-user-bubble">
                                {msg["content"]}
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f"""
                        <div class="inline-message-bubble">
                            <div class="inline-bubble-content inline-model-bubble">
                                {msg["content"]}
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

    # Input
    with st.form("inline_chat_form", clear_on_submit=True):
        col_input, col_send = st.columns([0.85, 0.15])
        with col_input:
            user_input = st.text_input(
                "Message",
                label_visibility="collapsed",
                placeholder="Scrivi qui il tuo messaggio...",
            )
        with col_send:
            sent = st.form_submit_button("➤", use_container_width=True)

        if sent and user_input:
            st.session_state.messages.append({"role": "user", "content": user_input})

            try:
                api_key = st.session_state.get("gemini_api_key")
                if not api_key:
                    st.session_state.messages.append(
                        {
                            "role": "assistant",
                            "content": "⚠️ API Key non configurata.\nConfigura la Gemini API Key nelle impostazioni.",
                        }
                    )
                    st.rerun()

                genai.configure(api_key=api_key)

                # -------------------------
                # Tools (GA4)
                # -------------------------
                def tool_list_properties() -> Any:
                    """Lista le property GA4 disponibili nell'account autenticato."""
                    return ga4_mcp_tools.get_account_summaries(creds)

                def tool_get_metadata(property_id: str) -> Any:
                    """Recupera dettagli/metadati della property GA4."""
                    return ga4_mcp_tools.get_property_details(property_id, creds)

                def tool_run_report(
                    property_id: str,
                    dimensions: List[str],
                    metrics: List[str],
                    start_date: str = "30daysAgo",
                    end_date: str = "today",
                ) -> Any:
                    """
                    Esegue un report GA4.
                    """
                    return ga4_mcp_tools.run_report(
                        property_id,
                        dimensions,
                        metrics,
                        [{"start_date": start_date, "end_date": end_date}],
                        creds,
                    )

                def tool_run_realtime_report(
                    property_id: str,
                    dimensions: List[str],
                    metrics: List[str]
                ) -> Any:
                    """Esegue un realtime report GA4."""
                    return ga4_mcp_tools.run_realtime_report(property_id, dimensions, metrics, creds)

                def tool_list_ads_links(property_id: str) -> Any:
                    """Lista i link Google Ads collegati alla property GA4."""
                    return ga4_mcp_tools.list_google_ads_links(property_id, creds)

                def tool_guess_property_from_url(destination_url: str) -> Dict[str, Any]:
                    """
                    Prova a indovinare la property GA4 a partire dall'URL di destinazione:
                    - lista le property
                    - fa matching sul dominio vs displayName (heuristic)
                    Ritorna una lista di candidati con punteggio.
                    """
                    url = _normalize_destination_url(destination_url)
                    host = urlparse(url).netloc.lower().replace("www.", "")
                    host_root = host.split(":")[0]

                    summaries = ga4_mcp_tools.get_account_summaries(creds)

                    # estrazione robusta: dipende da come ga4_mcp_tools serializza i summary
                    props = []
                    if isinstance(summaries, dict):
                        # prova chiavi comuni
                        for k in ["propertySummaries", "properties", "items", "data"]:
                            if k in summaries and isinstance(summaries[k], list):
                                props = summaries[k]
                                break
                        if not props and "accountSummaries" in summaries and isinstance(summaries["accountSummaries"], list):
                            # GA4 Admin API spesso ritorna accountSummaries -> propertySummaries
                            for acc in summaries["accountSummaries"]:
                                ps = acc.get("propertySummaries") or []
                                if isinstance(ps, list):
                                    props.extend(ps)
                    elif isinstance(summaries, list):
                        # lista di accountSummaries
                        for acc in summaries:
                            ps = acc.get("propertySummaries") or []
                            if isinstance(ps, list):
                                props.extend(ps)

                    candidates = []
                    for p in props:
                        display = (p.get("displayName") or p.get("name") or "").lower()
                        name = p.get("name") or ""  # spesso "properties/123"
                        pid = ""
                        m = re.search(r"properties/(\d+)", name)
                        if m:
                            pid = m.group(1)

                        score = 0
                        if host_root and host_root in display:
                            score += 3
                        # match su token (es. chicco)
                        token = host_root.split(".")[0] if host_root else ""
                        if token and token in display:
                            score += 2
                        if token and token in (p.get("displayName") or "").lower():
                            score += 1

                        candidates.append(
                            {
                                "property_id": pid,
                                "display_name": p.get("displayName") or "",
                                "score": score,
                            }
                        )

                    candidates.sort(key=lambda x: x["score"], reverse=True)
                    top = candidates[:5]

                    # Se tutte score 0, comunque ritorna top 5 per conferma manuale
                    return {
                        "normalized_url": url,
                        "domain": host_root,
                        "candidates": top,
                        "note": "Heuristic match su domain/displayName; conferma richiesta all'utente.",
                    }

                my_tools = [
                    tool_list_properties,
                    tool_get_metadata,
                    tool_run_report,
                    tool_run_realtime_report,
                    tool_list_ads_links,
                    tool_guess_property_from_url,
                ]

                # -------------------------
                # System instruction (aggiornata)
                # -------------------------
                current_date = datetime.now().strftime("%Y-%m-%d")

                system_instruction = f"""
Sei WR Assistant, un esperto nella generazione di parametri UTM.
Oggi è il {current_date}.

OBIETTIVO
Guidare l'utente a creare un URL tracciato che:
- rispetti le regole UTM definite
- sia coerente con lo storico GA4 (quando utile)
- finisca nel canale corretto secondo il channel grouping PRIMARIO della property

REGOLE VISIVE
1) Solo testo semplice (no HTML, no markdown complesso, no blocchi di codice).
2) UNA sola domanda per messaggio.
3) OUTPUT FINALE: stampa SOLO il link completo con un’istruzione del tipo "Copia e incolla questo link completo:".
   NON stampare JSON, NON usare parentesi graffe.

REGOLE ANTI-RIPETIZIONE
- Non ripetere i valori dell'utente in modo ridondante.
- Evita concatenazioni tipo "awarenessawareness".

REGOLE UTM (VALORI)
- utm_source / utm_medium / utm_campaign / utm_content / utm_term:
  - lowercase
  - senza spazi (usa underscore)
  - evita caratteri speciali: usa solo a-z 0-9 _ -
- Non inventare naming se esiste una convenzione storica.

REGOLE CANALI GA4
- Il CANALE dipende dal channel grouping della property.
- Usa dimensione "sessionPrimaryChannelGroup" (fallback: "sessionDefaultChannelGroup").

REGOLE GA4: QUANDO USARLO
- Non usare GA4 di default.
- Usalo quando:
  a) l’utente chiede verifica/storico (es. "ultimo anno")
  b) medium/source rischiano di mandare nel canale sbagliato
  c) servono opzioni coerenti con lo storico

PROPERTY GA4: NON chiedere property_id all’utente
- Quando hai un URL di destinazione, usa tool_guess_property_from_url(URL) per proporre 1-3 candidate property.
- Fai UNA domanda: "Ho trovato questa property: X (ID: Y). Confermi?"
- Se non conferma, proponi le altre candidate (una domanda).

FLOW (UNA DOMANDA PER STEP)
STEP 1: URL destinazione (normalizza a https://www.)
STEP 2: Contesto traffico (social, newsletter, paid search, display, altro)
STEP 3: Canale GA4 target (es. Organic Social / Paid Social / Email / Paid Search / Display / Referral / Direct / Other)
STEP 4: utm_medium
- Proponi 2-4 opzioni (meglio se da GA4 nel canale target):
  report: dimensions ["sessionPrimaryChannelGroup","sessionMedium"], metric ["sessions"]
STEP 5: utm_source
- Proponi 2-4 opzioni coerenti (meglio se da GA4 nel canale target):
  report: dimensions ["sessionPrimaryChannelGroup","sessionSource"], metric ["sessions"]
STEP 6: utm_campaign
Formato: market_type_name_date
- market: scegliere O country (es. IT) O lingua (es. it) — non entrambi
- date: formato GG-MM-AAAA (se l’utente inserisce altro formato, chiedi conferma conversione)
STEP 7: opzionali (utm_content, poi utm_term)
STEP 8: output finale SOLO LINK (con query correttamente formattata e senza caratteri speciali nei valori UTM).
"""

                # history
                history: List[Dict[str, Any]] = []
                for msg in st.session_state.messages:
                    role = "user" if msg["role"] == "user" else "model"
                    history.append({"role": role, "parts": [msg["content"]]})

                response_text, _used_model = get_gemini_response_safe(
                    user_input=user_input,
                    history=history,
                    tools=my_tools,
                    system_instruction=system_instruction,
                    api_key=api_key,
                )

                cleaned = clean_bot_response(response_text)
                st.session_state.messages.append({"role": "assistant", "content": cleaned})

            except Exception as e:
                st.session_state.messages.append({"role": "assistant", "content": f"❌ Errore: {str(e)}"})

            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)