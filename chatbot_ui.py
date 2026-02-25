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
# Multi-turn context tracking
# -------------------------
def _update_context_from_response(raw_response: str, user_input: str, context: dict) -> None:
    """
    Best-effort extraction of UTM parameters from Gemini responses and user input.
    Updates context in place. Never raises.
    """
    try:
        # Reset detection
        reset_phrases = ["ricominciamo", "nuovo link", "reset", "da capo", "riparti"]
        if any(phrase in (user_input or "").lower() for phrase in reset_phrases):
            context["current_step"] = 0
            for k in context["params"]:
                context["params"][k] = None
            context["ga4_property_id"] = None
            context["tool_cache"] = {}
            return

        # Extract URL from user input
        url = _extract_first_url(user_input)
        if url and not context["params"]["destination_url"]:
            context["params"]["destination_url"] = _normalize_destination_url(url)

        # Parse JSON blocks from raw response for utm_* keys
        json_data = _extract_json_block_if_any(raw_response or "")
        if json_data:
            for key in ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"]:
                val = json_data.get(key)
                if val and str(val).lower() not in ("null", "none", ""):
                    context["params"][key] = str(val)
            for url_key in ["url", "URL", "destination_url"]:
                val = json_data.get(url_key)
                if val and str(val).strip():
                    context["params"]["destination_url"] = _normalize_destination_url(str(val))

        # Infer traffic_type from user input
        if not context["params"]["traffic_type"]:
            for traffic in ["social", "newsletter", "email", "paid search", "display", "referral"]:
                if traffic in (user_input or "").lower():
                    context["params"]["traffic_type"] = traffic
                    break

        # Infer ga4_channel from user input
        if not context["params"]["ga4_channel"]:
            channel_keywords = {
                "organic social": "Organic Social",
                "paid social": "Paid Social",
                "email": "Email",
                "paid search": "Paid Search",
                "display": "Display",
                "referral": "Referral",
            }
            for kw, channel in channel_keywords.items():
                if kw in (user_input or "").lower():
                    context["params"]["ga4_channel"] = channel
                    break

        # Extract utm values from user input using common patterns
        input_lower = (user_input or "").lower()
        utm_patterns = {
            "utm_medium": r"(?:utm_?medium|medium)\s*[:=è]\s*([a-z0-9_-]+)",
            "utm_source": r"(?:utm_?source|source)\s*[:=è]\s*([a-z0-9_-]+)",
            "utm_campaign": r"(?:utm_?campaign|campaign)\s*[:=è]\s*([a-z0-9_-]+)",
            "utm_content": r"(?:utm_?content|content)\s*[:=è]\s*([a-z0-9_-]+)",
            "utm_term": r"(?:utm_?term|term)\s*[:=è]\s*([a-z0-9_-]+)",
        }
        for param, pattern in utm_patterns.items():
            if not context["params"][param]:
                m = re.search(pattern, input_lower)
                if m:
                    context["params"][param] = m.group(1)

        # Advance current_step based on filled params (never goes backward)
        step_map = [
            "destination_url",   # step 1
            "traffic_type",      # step 2
            "ga4_channel",       # step 3
            "utm_medium",        # step 4
            "utm_source",        # step 5
            "utm_campaign",      # step 6
        ]
        filled = 0
        for param_name in step_map:
            if context["params"].get(param_name):
                filled += 1
            else:
                break
        new_step = max(context["current_step"], filled)
        if filled >= 6:
            has_optional = context["params"].get("utm_content") or context["params"].get("utm_term")
            if has_optional:
                new_step = max(new_step, 7)
        context["current_step"] = new_step

    except Exception:
        pass  # Never break the chat


def _build_system_instruction(context: dict, current_date: str) -> str:
    """
    Builds the system instruction with static rules, skill guidelines,
    and dynamic conversation state.
    """
    def _val(key: str) -> str:
        v = context["params"].get(key)
        return v if v else "non ancora fornito"

    step_descriptions = {
        0: "Chiedi l'URL di destinazione (step 1)",
        1: "Chiedi il contesto del traffico - social, newsletter, paid search, display, altro (step 2)",
        2: "Chiedi il canale GA4 target (step 3)",
        3: "Proponi opzioni per utm_medium (step 4)",
        4: "Proponi opzioni per utm_source (step 5)",
        5: "Chiedi utm_campaign nel formato country-lingua_type_name_date (step 6)",
        6: "Chiedi parametri opzionali utm_content e utm_term (step 7)",
        7: "Genera il link finale completo (step 8)",
    }
    next_step = min(context["current_step"], 7)
    next_desc = step_descriptions.get(next_step, "Genera il link finale completo (step 8)")

    ga4_val = context.get("ga4_property_id") or "non ancora selezionata"

    base = f"""Sei WR Assistant, un esperto nella generazione di parametri UTM.
Oggi è il {current_date}.

OBIETTIVO
Guidare l'utente a creare un URL tracciato che:
- rispetti le regole UTM definite
- sia coerente con lo storico GA4 (quando utile)
- finisca nel canale corretto secondo il channel grouping PRIMARIO della property

REGOLE VISIVE
1) Solo testo semplice (no HTML, no markdown complesso, no blocchi di codice).
2) UNA sola domanda per messaggio.
3) OUTPUT FINALE: stampa SOLO il link completo con un'istruzione del tipo "Copia e incolla questo link completo:".
   NON stampare JSON, NON usare parentesi graffe.

REGOLE ANTI-RIPETIZIONE
- Non ripetere i valori dell'utente in modo ridondante.
- Evita concatenazioni tipo "awarenessawareness".

REGOLE UTM (VALORI)
- utm_source (mandatory): fonte/origine del traffico
- utm_medium (mandatory): mezzo/canale attraverso cui arriva il traffico
- utm_campaign (mandatory): nome della singola campagna
- utm_term (optional): keyword / caratteristiche della campagna
- utm_content (optional): differenziare contenuti simili o dettaglio significativo
Naming convention:
- Solo lowercase (case-sensitive: "Facebook" != "facebook")
- No spazi e no caratteri speciali: usare _ o -. Evitare ? % & $ !
- Coerenza: definire una struttura e seguirla
- Descrittivo ma conciso
- Trattini dentro i token per separare parole, underscore tra token
- Non inventare naming se esiste una convenzione storica.

MAPPING utm_medium / utm_source (DA PROPORRE IN BASE AL traffic_type)
- Organic: medium=organic, source=google|bing|yahoo|yandex
- Referral: medium=referral, source=[website domain]
- Direct: medium=(none), source=(direct)
- Paid campaign: medium=cpc, source=google|bing
- Affiliate: medium=affiliate, source=tradetracker
- Display: medium=cpm, source=reservation|display|programmatic_video
- Video: medium=cpv, source=youtube
- Programmatic: medium=cpm, source=rcs|mediamond|rai|ilsole24ore
- Email/Newsletter: medium=email oppure mailing_campaign, source=newsletter|email|crm
- Social organic: medium=social_org, source=facebook|instagram|linkedin|...(nome social)
- Social paid: medium=social_paid, source=facebook|instagram|linkedin|...(nome social)
- App traffic: medium=(chiedere all'utente), source=app
- Offline: medium=offline, source=brochure|qr_code|sms

REGOLE utm_campaign (STRUTTURA OBBLIGATORIA)
Formato: country-lingua_campaignType_campaignName_data[_CTA]
Token separati da underscore _, parole dentro un token separate da trattino -.
Token richiesti:
1) country-lingua: indica la provenienza/lingua della campagna. È sufficiente inserire UNO dei due: solo il paese (es. it, ch, es) OPPURE paese-lingua (es. it-it, ch-de, es-es). Non è obbligatorio fornire entrambi. Esempi validi: "it", "ch", "it-it", "ch-de".
2) campaignType: uno tra promo (promotional), ed (editorial), tr (transactional), awr (awareness)
3) campaignName: nome interno della campagna
4) data: data invio/riferimento temporale (formato GG-MM-AAAA consigliato)
Token opzionale:
5) CTA: es. cta, image, banner
Golden rules: struttura obbligatoria, token mandatory presenti, _ tra token, - dentro token, no spazi/% /&.

REGOLE utm_term
- Utile per keyword e caratteristiche specifiche
- Esempi categorie: nursing, toys, indoor, fashion, toiletries, car-seat, outdoor

VALIDAZIONI DA APPLICARE
1) Blocca se mancano: utm_source, utm_medium, utm_campaign, base_url
2) Controlla utm_campaign: token separati da _, minimo 4 token, no spazi/%/&
3) Forza lowercase su tutti i parametri
4) Sostituisci spazi con - nei valori

COSTRUZIONE URL
- Forma: https://www.tuosito.it?utm_source=...&utm_medium=...&utm_campaign=...
- ? separa URL base e parametri, & unisce i parametri
- Se base_url contiene già ?, aggiungi UTM con & (non duplicare ?)

REGOLE CANALI GA4
- Il CANALE dipende dal channel grouping della property.
- Usa dimensione "sessionPrimaryChannelGroup" (fallback: "sessionDefaultChannelGroup").

REGOLE GA4: QUANDO USARLO
- Non usare GA4 di default.
- Usalo quando:
  a) l'utente chiede verifica/storico (es. "ultimo anno")
  b) medium/source rischiano di mandare nel canale sbagliato
  c) servono opzioni coerenti con lo storico

GESTIONE ERRORI GA4
- Se un tool GA4 restituisce un dict con chiave "error", riporta all'utente il messaggio esatto: es. "Errore GA4: <valore di error>".
- Se l'errore contiene "error_type", segnalalo: es. "Tipo: PermissionDenied".
- Non assumere che sia sempre un problema di permessi: potrebbe essere un token scaduto, uno scope mancante, o un property_id errato.
- Se GA4 non è disponibile, continua comunque il flusso UTM usando le regole statiche e i mapping definiti sopra.
- Non bloccare il flusso UTM a causa di errori GA4: prosegui e proponi opzioni basate sulle regole.

PROPERTY GA4: NON chiedere property_id all'utente
- Quando hai un URL di destinazione, usa tool_guess_property_from_url(URL) per proporre 1-3 candidate property.
- Fai UNA domanda: "Ho trovato questa property: X (ID: Y). Confermi?"
- Se non conferma, proponi le altre candidate (una domanda).

FLOW (UNA DOMANDA PER STEP)
STEP 1: URL destinazione (normalizza a https://www.)
STEP 2: Contesto traffico (social, newsletter, paid search, display, altro)
STEP 3: Canale GA4 target (es. Organic Social / Paid Social / Email / Paid Search / Display / Referral / Direct / Other)
STEP 4: utm_medium
- Proponi 2-4 opzioni coerenti col traffic_type (vedi MAPPING sopra)
- Se possibile, verifica con GA4: dimensions ["sessionPrimaryChannelGroup","sessionMedium"], metric ["sessions"]
STEP 5: utm_source
- Proponi 2-4 opzioni coerenti (vedi MAPPING sopra)
- Se possibile, verifica con GA4: dimensions ["sessionPrimaryChannelGroup","sessionSource"], metric ["sessions"]
STEP 6: utm_campaign
- Costruisci chiedendo solo i token mancanti:
  1) country-lingua, 2) campaignType (mostra opzioni: promo/ed/tr/awr), 3) campaignName, 4) data, 5) CTA (opzionale)
STEP 7: opzionali (utm_content, poi utm_term)
STEP 8: output finale SOLO LINK (con query correttamente formattata e senza caratteri speciali nei valori UTM).

STATO ATTUALE DELLA CONVERSAZIONE
- Step attuale: {next_step} di 8
- Parametri raccolti:
  - URL destinazione: {_val("destination_url")}
  - Tipo di traffico: {_val("traffic_type")}
  - Canale GA4 target: {_val("ga4_channel")}
  - utm_medium: {_val("utm_medium")}
  - utm_source: {_val("utm_source")}
  - utm_campaign: {_val("utm_campaign")}
  - utm_content: {_val("utm_content")}
  - utm_term: {_val("utm_term")}
- Property GA4: {ga4_val}

ISTRUZIONI BASATE SULLO STATO
- Non chiedere nuovamente i parametri già raccolti sopra.
- Il prossimo step da completare è: {next_desc}
- Se l'utente fornisce più parametri in un solo messaggio, raccoglili tutti e avanza.
"""
    return base


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
        "❌ Impossibile trovare un modello Gemini attivo per questa API Key.\\n"
        f"Ultimo errore: {str(last_error)}\\n"
    )


# -------------------------
# Main UI
# -------------------------
def render_chatbot_interface(creds, api_key_func=None) -> None:
    """
    Renderizza il widget Chatbot in modalità Floating (FAB + Window).
    """
    # Stato
    if "chat_visible" not in st.session_state:
        st.session_state.chat_visible = False
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "chat_is_responding" not in st.session_state:
        st.session_state.chat_is_responding = False
    if "pending_user_text" not in st.session_state:
        st.session_state.pending_user_text = None
    if "utm_context" not in st.session_state:
        st.session_state.utm_context = {
            "current_step": 0,
            "params": {
                "destination_url": None,
                "traffic_type": None,
                "ga4_channel": None,
                "utm_medium": None,
                "utm_source": None,
                "utm_campaign": None,
                "utm_content": None,
                "utm_term": None,
            },
            "ga4_property_id": None,
            "tool_cache": {},
        }

    # Carica icona
    base_path = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(base_path, "wr_assistant_icon.png.png")
    icon_b64 = get_base64_image(icon_path)
    
    # CSS per Floating Button e Window
    # Usa selettori molto specifici e un container ID unico per evitare conflitti
    
    # 1. STYLE PER IL BUTTON (FAB)
    # CSS per Floating Button e Window
    # Usa selettori molto specifici e un container ID unico per evitare conflitti
    
    # 1. STYLE PER IL BUTTON (FAB)
    fab_css = f"""
        /* Targettiamo SOLO la colonna specifica che contiene il nostro marker univoco */
        /* Questo evita di matchare il main container o blocchi generici che contengono altri bottoni */
        div[data-testid="stColumn"]:has(div.fab-unique-marker) {{
            position: fixed;
            bottom: 30px;
            right: 30px;
            width: auto !important;
            height: auto !important;
            z-index: 999999;
            background: transparent !important;
            pointer-events: none;
            overflow: visible !important; /* Importante per far uscire il fixed */
        }}
        
        div[data-testid="stColumn"]:has(div.fab-unique-marker) button {{
            pointer-events: auto;
            width: 70px !important;
            height: 70px !important;
            border-radius: 50% !important;
            border: none !important;
            box-shadow: 0 6px 16px rgba(0,0,0,0.2) !important;
            transition: transform 0.2s, box-shadow 0.2s !important;
            background-color: white !important;
            background-size: cover !important;
            background-position: center !important;
            background-repeat: no-repeat !important;
            display: block !important;
            margin: 0 !important;
        }}
        
        div[data-testid="stColumn"]:has(div.fab-unique-marker) button:hover {{
            transform: scale(1.05);
            box-shadow: 0 8px 20px rgba(0,0,0,0.3) !important;
        }}
        
        div[data-testid="stColumn"]:has(div.fab-unique-marker) button p {{
            display: none !important;
        }}
        
        /* Nasconde il marker stesso */
        .fab-unique-marker {{
            display: none;
        }}
    """
    
    if icon_b64:
        fab_css += f"""
        div[data-testid="stColumn"]:has(div.fab-unique-marker) button {{
            background-image: url("data:image/png;base64,{icon_b64}") !important;
        }}
        """
    else:
        fab_css += """
        div[data-testid="stColumn"]:has(div.fab-unique-marker) button {
            background-color: #2563eb !important;
        }
        div[data-testid="stColumn"]:has(div.fab-unique-marker) button::after {
            content: "💬";
            font-size: 30px;
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100%;
            color: white;
        }
        """

    # 2. STYLE PER LA WINDOW
    window_css = """
        /* ------------------------------------------------
         * CHAT WINDOW: fixed overlay, non disturba il layout
         * Il selector prende il vertical block piu' interno
         * con marker dedicato per evitare side effect sui parent.
         * ------------------------------------------------ */
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope)) {
            position: fixed;
            bottom: 110px;
            right: 30px;
            width: 380px !important;
            max-width: 90vw;
            height: 600px !important;
            max-height: 80vh;
            background-color: white;
            border-radius: 16px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.15);
            z-index: 999998;
            border: 1px solid #e5e7eb;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            padding: 0 !important;
            gap: 0 !important;
        }

        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            > div[data-testid="element-container"] {
            margin-bottom: 0 !important;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            > div[data-testid="element-container"]:last-child {
            margin-bottom: 0 !important;
            padding-bottom: 0 !important;
        }

        /* Scroll storico messaggi in area dedicata */
        .chat-messages-area {
            height: clamp(180px, 48vh, 360px);
            min-height: 0;
            overflow-y: auto;
            padding: 10px 8px;
            display: flex;
            flex-direction: column-reverse;
            gap: 8px;
            background: #f9fafb;
            flex: 0 0 auto;
            overflow-anchor: none;
        }

        /* Input area dentro la window */
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            > div[data-testid="element-container"]:has(div[data-testid="stForm"]) {
            margin-top: auto !important;
            margin-bottom: 0 !important;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="stForm"] {
            padding: 8px 8px 0 !important;
            border-top: 1px solid #e5e7eb;
            background: white;
            position: sticky;
            bottom: 0;
            z-index: 3;
            margin-bottom: 0 !important;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="stForm"] form {
            margin-bottom: 0 !important;
            padding-bottom: 0 !important;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="stFormSubmitButton"] {
            margin-bottom: 0 !important;
            padding-bottom: 0 !important;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="element-container"]:has([data-testid="stSpinner"]) {
            display: none !important;
        }

        .chat-header {
            background: #2563eb;
            color: white;
            padding: 12px 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-weight: 600;
            font-size: 15px;
            border-bottom: 1px solid #1d4ed8;
            flex-shrink: 0;
        }

        .msg-bubble {
            padding: 10px 14px;
            border-radius: 12px;
            font-size: 14px;
            line-height: 1.5;
            max-width: 85%;
            word-wrap: break-word;
        }
        .msg-user {
            background: #2563eb;
            color: white;
            align-self: flex-end;
            border-bottom-right-radius: 2px;
        }
        .msg-bot {
            background: white;
            color: #1f2937;
            border: 1px solid #e5e7eb;
            align-self: flex-start;
            border-bottom-left-radius: 2px;
            box-shadow: 0 1px 2px rgba(0,0,0,0.05);
        }
        .msg-loading {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            color: #334155;
            background: #eff6ff;
            border-color: #bfdbfe;
        }
        .chat-loader {
            width: 14px;
            height: 14px;
            border-radius: 50%;
            border: 2px solid #bfdbfe;
            border-top-color: #2563eb;
            animation: chat-loader-spin .8s linear infinite;
            flex-shrink: 0;
        }
        @keyframes chat-loader-spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }
    """

    st.markdown(f"<style>{fab_css}{window_css}</style>", unsafe_allow_html=True)

    # Marker esterno: collassa l'intera sezione chatbot nel layout Streamlit
    # in modo che non occupi spazio verticale nella pagina
    st.markdown('<div class="chatbot-outer-marker" style="display:none;"></div>', unsafe_allow_html=True)

    # 1. FLOATING BUTTON CONTAINER
    # Usiamo una colonna isolata (st.columns crea un wrapper specifico diverso dal main flow)
    # Questo ci permette di targettare div[data-testid="stColumn"] ed evitare collisioni con i bottoni nel main flow
    c_fab = st.columns([1])[0]
    with c_fab:
        st.markdown('<div class="fab-unique-marker">marker</div>', unsafe_allow_html=True)
        if st.button("WR", key="fab_main_toggle"):
            st.session_state.chat_visible = not st.session_state.chat_visible
            st.rerun()

    # 2. CHAT WINDOW CONTAINER
    if st.session_state.chat_visible:
        with st.container():
            st.markdown('<div class="chat-window-scope" style="display:none;"></div>', unsafe_allow_html=True)
            
            # HEADER
            c_h1, c_h2 = st.columns([0.85, 0.15])
            with c_h1:
                st.markdown('<div style="font-weight:600; color:#1f2937; margin-top:5px; margin-left:5px;">🤖 WR Assistant</div>', unsafe_allow_html=True)
            with c_h2:
                if st.button("✕", key="close_window_btn"):
                    st.session_state.chat_visible = False
                    st.rerun()
                    
            st.markdown('<div style="height:1px; background:#e5e7eb; margin: 10px 0;"></div>', unsafe_allow_html=True)

            # MESSAGES – render come HTML puro per evitare spazio nel layout Streamlit
            if not st.session_state.messages and not st.session_state.chat_is_responding:
                img_tag = f'<img src="data:image/png;base64,{icon_b64}" style="width:60px;height:60px;margin-bottom:12px;opacity:0.8;border-radius:50%;"><br>' if icon_b64 else ''
                msgs_html = f'<div class="chat-messages-area"><div style="text-align:center;padding:30px 16px;color:#6b7280;font-size:14px;">{img_tag}<b>Ciao!</b><br>Sono qui per aiutarti coi parametri UTM.</div></div>'
            else:
                rows = []
                if st.session_state.chat_is_responding:
                    rows.append(
                        '<div style="display:flex;justify-content:flex-start;margin-bottom:6px;">'
                        '<div class="msg-bubble msg-bot msg-loading"><span class="chat-loader"></span>'
                        'WR Assistant sta rispondendo...</div></div>'
                    )

                for msg in reversed(st.session_state.messages):
                    content = msg["content"].replace("\n", "<br>")
                    if msg["role"] == "user":
                        rows.append(f'<div style="display:flex;justify-content:flex-end;margin-bottom:6px;"><div class="msg-bubble msg-user">{content}</div></div>')
                    else:
                        rows.append(f'<div style="display:flex;justify-content:flex-start;margin-bottom:6px;"><div class="msg-bubble msg-bot">{content}</div></div>')

                msgs_html = '<div class="chat-messages-area">' + ''.join(rows) + '</div>'
            st.markdown(msgs_html, unsafe_allow_html=True)

            # INPUT
            chat_locked = bool(st.session_state.chat_is_responding)
            input_placeholder = "WR Assistant sta rispondendo..." if chat_locked else "Scrivi qui..."

            with st.form("chat_input_form", clear_on_submit=True):
                user_text = st.text_input(
                    "Messaggio",
                    label_visibility="collapsed",
                    placeholder=input_placeholder,
                    disabled=chat_locked,
                )
                submitted = st.form_submit_button("Invia", use_container_width=True, disabled=chat_locked)

            if submitted and user_text and not chat_locked:
                st.session_state.messages.append({"role": "user", "content": user_text})
                st.session_state.pending_user_text = user_text
                st.session_state.chat_is_responding = True
                st.rerun()

            if st.session_state.chat_is_responding and st.session_state.pending_user_text:
                pending_text = st.session_state.pending_user_text

                try:
                    with st.spinner("WR Assistant sta rispondendo..."):
                        api_key = st.session_state.get("gemini_api_key")
                        if not api_key:
                            st.session_state.messages.append(
                                {"role": "assistant", "content": "Configura prima la API Key nelle impostazioni."}
                            )
                        else:
                            genai.configure(api_key=api_key)
                            utm_ctx = st.session_state.utm_context

                            # --- TOOLS ---
                            def tool_list_properties() -> Any:
                                cache_key = "list_properties"
                                if cache_key in utm_ctx["tool_cache"]:
                                    return utm_ctx["tool_cache"][cache_key]
                                result = ga4_mcp_tools.get_account_summaries(creds)
                                utm_ctx["tool_cache"][cache_key] = result
                                return result

                            def tool_get_metadata(property_id: str) -> Any:
                                return ga4_mcp_tools.get_property_details(property_id, creds)

                            def tool_run_report(property_id: str, dimensions: List[str], metrics: List[str], start_date: str = "30daysAgo", end_date: str = "today") -> Any:
                                cache_key = f"run_report:{property_id}:{dimensions}:{metrics}:{start_date}:{end_date}"
                                if cache_key in utm_ctx["tool_cache"]:
                                    return utm_ctx["tool_cache"][cache_key]
                                result = ga4_mcp_tools.run_report(property_id, dimensions, metrics, [{"start_date": start_date, "end_date": end_date}], creds)
                                utm_ctx["tool_cache"][cache_key] = result
                                return result

                            def tool_run_realtime_report(property_id: str, dimensions: List[str], metrics: List[str]) -> Any:
                                return ga4_mcp_tools.run_realtime_report(property_id, dimensions, metrics, creds)

                            def tool_list_ads_links(property_id: str) -> Any:
                                return ga4_mcp_tools.list_google_ads_links(property_id, creds)

                            def tool_guess_property_from_url(destination_url: str) -> Dict[str, Any]:
                                cache_key = f"guess_property:{destination_url}"
                                if cache_key in utm_ctx["tool_cache"]:
                                    return utm_ctx["tool_cache"][cache_key]
                                url = _normalize_destination_url(destination_url)
                                host = urlparse(url).netloc.lower().replace("www.", "")
                                host_root = host.split(":")[0]
                                summaries = ga4_mcp_tools.get_account_summaries(creds)
                                props = []
                                if isinstance(summaries, dict):
                                    for k in ["propertySummaries", "properties", "items", "data"]:
                                        if k in summaries and isinstance(summaries[k], list):
                                            props = summaries[k]
                                            break
                                    if not props and "accountSummaries" in summaries:
                                        for acc in summaries["accountSummaries"]:
                                            ps = acc.get("propertySummaries") or []
                                            if isinstance(ps, list):
                                                props.extend(ps)
                                elif isinstance(summaries, list):
                                    for acc in summaries:
                                        ps = acc.get("propertySummaries") or []
                                        if isinstance(ps, list):
                                            props.extend(ps)

                                candidates = []
                                for p in props:
                                    display = (p.get("displayName") or p.get("name") or "").lower()
                                    pid = ""
                                    m = re.search(r"properties/(\d+)", p.get("name") or "")
                                    if m:
                                        pid = m.group(1)
                                    score = 0
                                    if host_root and host_root in display:
                                        score += 3
                                    candidates.append(
                                        {"property_id": pid, "display_name": p.get("displayName"), "score": score}
                                    )

                                candidates.sort(key=lambda x: x["score"], reverse=True)
                                result = {"candidates": candidates[:5], "domain": host_root}
                                utm_ctx["tool_cache"][cache_key] = result
                                return result

                            my_tools = [
                                tool_list_properties,
                                tool_get_metadata,
                                tool_run_report,
                                tool_run_realtime_report,
                                tool_list_ads_links,
                                tool_guess_property_from_url,
                            ]

                            # --- Dynamic system instruction ---
                            current_date = datetime.now().strftime("%Y-%m-%d")
                            system_instruction = _build_system_instruction(utm_ctx, current_date)

                            # --- History ---
                            history = []
                            for msg in st.session_state.messages:
                                if msg == st.session_state.messages[-1]:
                                    continue
                                role = "user" if msg["role"] == "user" else "model"
                                text = msg.get("raw_content", msg["content"])
                                history.append({"role": role, "parts": [text]})

                            response_text, _ = get_gemini_response_safe(
                                pending_text,
                                history,
                                my_tools,
                                system_instruction,
                                api_key,
                            )
                            cleaned = clean_bot_response(response_text)

                            st.session_state.messages.append(
                                {
                                    "role": "assistant",
                                    "content": cleaned,
                                    "raw_content": response_text,
                                }
                            )

                            # Update conversation context
                            _update_context_from_response(response_text, pending_text, utm_ctx)

                except Exception as e:
                    st.session_state.messages.append({"role": "assistant", "content": f"Errore: {str(e)}"})
                finally:
                    st.session_state.chat_is_responding = False
                    st.session_state.pending_user_text = None

                st.rerun()
