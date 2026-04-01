import streamlit as st
import streamlit.components.v1 as components
import re
import json
import hashlib
import html as html_lib
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

import google.generativeai as genai
import ga4_mcp_tools  # Importa il modulo con i tool GA4


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
        url = m.group(1).strip()
        return re.sub(r"[`\"'.,;:)\]]+$", "", url)

    # 2) URL tipo www.sito.it/...
    m = re.search(r"\b(www\.[^\s]+)\b", text)
    if m:
        url = m.group(1).strip()
        return re.sub(r"[`\"'.,;:)\]]+$", "", url)

    # 3) URL tipo dominio.tld/...
    m = re.search(r"\b([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})(/[^\s]*)?\b", text)
    if m:
        url = (m.group(1) + (m.group(2) or "")).strip()
        return re.sub(r"[`\"'.,;:)\]]+$", "", url)

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
    Accetta input comuni e restituisce data in formato GGMMAAAA.
    Esempi supportati:
    - 2026-02-10 -> 10022026
    - 10.02.26 -> 10022026
    - 10/02/2026 -> 10022026
    - 10-02-2026 -> 10022026
    """
    if not date_str:
        return None

    s = date_str.strip()

    # YYYY-MM-DD
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        yyyy, mm, dd = m.group(1), m.group(2), m.group(3)
        return f"{dd}{mm}{yyyy}"

    # DD.MM.YY or DD.MM.YYYY
    m = re.match(r"^(\d{2})\.(\d{2})\.(\d{2,4})$", s)
    if m:
        dd, mm, yy = m.group(1), m.group(2), m.group(3)
        if len(yy) == 2:
            yy = "20" + yy
        return f"{dd}{mm}{yy}"

    # DD/MM/YYYY
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", s)
    if m:
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        return f"{dd}{mm}{yyyy}"

    # DD-MM-YYYY
    m = re.match(r"^(\d{2})-(\d{2})-(\d{4})$", s)
    if m:
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        return f"{dd}{mm}{yyyy}"

    return None


def _normalize_utm_campaign_date_token(utm_campaign: str) -> str:
    """
    Normalizza la componente data dentro utm_campaign al formato GGMMAAAA.
    Esempio: it_awr_saldi_27-02-2026_cta -> it_awr_saldi_27022026_cta
    """
    value = (utm_campaign or "").strip().replace("`", "")
    if not value:
        return value
    parts = value.split("_")
    for i, part in enumerate(parts):
        fixed = _try_fix_date_to_ddmmyyyy(part)
        if fixed:
            parts[i] = fixed
            break
    return "_".join(parts)


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
    text = text.replace("`", "")
    text = text.replace("**", "")
    # rimuove escape markdown superflui (es. social\_paid -> social_paid)
    text = text.replace("\\_", "_")
    text = text.replace("\\[", "[").replace("\\]", "]")
    # guard-rail su artefatti multilingua occasionali
    text = text.replace("দেশ/lingua", "country/lingua")

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
            clean_v = str(v).replace("`", "").strip()
            if k == "utm_campaign":
                clean_v = _normalize_utm_campaign_date_token(clean_v)
            utm_pairs.append((k, clean_v))

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
        p = urlparse(norm)
        pairs = parse_qsl(p.query, keep_blank_values=True)
        cleaned_pairs = []
        for key, value in pairs:
            clean_value = (value or "").replace("`", "").strip()
            if key == "utm_campaign":
                clean_value = _normalize_utm_campaign_date_token(clean_value)
            cleaned_pairs.append((key, clean_value))
        encoded = urlencode(cleaned_pairs, doseq=True, safe="")
        fixed = urlunparse((p.scheme, p.netloc, p.path, p.params, encoded, p.fragment))
        fixed = _rebuild_url_with_encoded_query(fixed)

        # Se il bot ha scritto testo + url, mantieni solo l’istruzione + url
        # (per rispettare la richiesta “output solo link”)
        if "utm_" in fixed:
            return "Copia e incolla questo link completo:\n" + fixed

    return text


def _extract_client_rule_constraints(client_rules_text: str) -> Tuple[List[str], List[str], Dict[str, List[str]]]:
    allowed_sources: List[str] = []
    allowed_mediums: List[str] = []
    medium_source_map: Dict[str, List[str]] = {}

    for raw_line in str(client_rules_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        source_match = re.search(r"utm_source consentiti \(esempi\):\s*(.+)$", line, flags=re.IGNORECASE)
        if source_match:
            allowed_sources = [_sanitize_utm_value(x) for x in source_match.group(1).split(",")]
            allowed_sources = [x for x in allowed_sources if x]
            continue

        medium_match = re.search(r"utm_medium consentiti \(esempi\):\s*(.+)$", line, flags=re.IGNORECASE)
        if medium_match:
            allowed_mediums = [_sanitize_utm_value(x) for x in medium_match.group(1).split(",")]
            allowed_mediums = [x for x in allowed_mediums if x]
            continue

        mapping_match = re.search(
            r"mapping utm_source per utm_medium=([a-z0-9_-]+):\s*(.+)$",
            line,
            flags=re.IGNORECASE,
        )
        if mapping_match:
            medium = _sanitize_utm_value(mapping_match.group(1))
            values = [_sanitize_utm_value(x) for x in mapping_match.group(2).split(",")]
            values = [x for x in values if x]
            if medium and values:
                medium_source_map[medium] = values

    return allowed_sources, allowed_mediums, medium_source_map


def _enforce_client_rule_options(raw_text: str, context: dict, client_rules_text: str) -> str:
    text = str(raw_text or "").strip()
    if not text or not client_rules_text:
        return text

    if "http" in text and "utm_" in text:
        return text

    _allowed_sources, _allowed_mediums, medium_source_map = _extract_client_rule_constraints(client_rules_text)
    if not medium_source_map:
        return text

    low = text.lower()
    current_medium = _sanitize_utm_value(str(context.get("params", {}).get("utm_medium") or ""))
    if not current_medium:
        return text

    allowed_for_medium = medium_source_map.get(current_medium) or []
    if not allowed_for_medium:
        return text

    is_source_step = (
        "utm_source" in low
        or "origine del traffico" in low
        or "passiamo a utm_source" in low
    )
    if not is_source_step:
        return text

    if len(allowed_for_medium) == 1:
        only = allowed_for_medium[0]
        return (
            f"Ottimo. Ora passiamo a utm_source. Per utm_medium={current_medium}, "
            f"la convenzione cliente prevede un solo valore coerente: {only}. "
            f"Confermi di utilizzare utm_source={only}?"
        )

    allowed_csv = ", ".join(allowed_for_medium)
    return (
        f"Ottimo. Ora passiamo a utm_source. Per utm_medium={current_medium}, "
        f"i valori coerenti previsti dalla convenzione cliente sono: {allowed_csv}. "
        "Quale vuoi usare?"
    )


def _infer_optional_value_from_text(user_input: str) -> str:
    plain = str(user_input or "").strip().lower()
    if not plain:
        return ""
    tokens = re.findall(r"[a-zA-Z0-9àèéìòù_-]+", plain)
    stopwords = {
        "si", "sì", "no", "ok", "va", "bene", "usa", "usiamo", "metti", "mettere",
        "lascia", "vuoto", "nessuno", "nessuna", "niente", "senza", "utm", "content",
        "term", "cta", "keyword", "keywords", "target", "audience", "segmento",
    }
    kept = []
    for token in tokens:
        clean = _sanitize_utm_value(token)
        if not clean or clean in stopwords or clean.isdigit():
            continue
        kept.append(clean)
        if len(kept) >= 4:
            break
    return "-".join(kept)


def _enforce_optional_followup(raw_text: str, context: dict) -> str:
    text = str(raw_text or "").strip()
    if not text:
        return text

    params = context.get("params", {})
    if not params.get("utm_campaign"):
        return text

    optional_step = str(context.get("optional_step") or "")
    low = text.lower()
    already_mentions_optional = any(
        key in low for key in ["utm_content", "utm_term", "cta", "keyword", "segmento", "audience"]
    )
    if already_mentions_optional:
        return text

    if optional_step == "content" and not params.get("utm_content"):
        return (
            "Perfetto. Prima del link finale vuoi valorizzare anche utm_content? "
            "Per esempio possiamo inserire il nome della CTA, del bottone, del banner o del visual principale."
        )

    if optional_step == "term" and not params.get("utm_term"):
        return (
            "Perfetto. Vuoi aggiungere anche utm_term? "
            "Se ti serve, possiamo usarlo per keyword, audience, segmento o dettaglio dell'offerta; altrimenti dimmi pure di lasciarlo vuoto."
        )

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
        reset_phrases = ["ricominciamo", "nuovo link", "reset", "da capo", "riparti"]
        if any(phrase in (user_input or "").lower() for phrase in reset_phrases):
            context["current_step"] = 0
            for k in context["params"]:
                context["params"][k] = None
            context["ga4_property_id"] = None
            context["tool_cache"] = {}
            context["optional_step"] = "content"
            return

        plain_input = str(user_input or "").strip()
        input_lower = plain_input.lower()
        params = context["params"]

        url = _extract_first_url(user_input)
        if url and not params["destination_url"]:
            params["destination_url"] = _normalize_destination_url(url)

        has_explicit_utm = any(tag in input_lower for tag in ["utm_", "utm source", "utm medium", "utm campaign"])
        if plain_input and len(plain_input.split()) >= 5 and not has_explicit_utm and not params.get("campaign_brief"):
            params["campaign_brief"] = plain_input

        json_data = _extract_json_block_if_any(raw_response or "")
        if json_data:
            for key in ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"]:
                val = json_data.get(key)
                if val and str(val).lower() not in ("null", "none", ""):
                    params[key] = str(val)
            for url_key in ["url", "URL", "destination_url"]:
                val = json_data.get(url_key)
                if val and str(val).strip():
                    params["destination_url"] = _normalize_destination_url(str(val))

        if not params["traffic_type"]:
            traffic_aliases = {
                "newsletter": ["newsletter", "dem", "email marketing", "mailing", "invio email"],
                "paid search": ["paid search", "google ads", "search ads", "sem", "ppc", "campagna search"],
                "display": ["display", "banner", "programmatic", "gdn", "retargeting display"],
                "social": ["social", "meta ads", "facebook ads", "instagram ads", "linkedin ads", "tiktok ads"],
                "referral": ["referral", "partnership", "affiliato", "affiliate", "sito partner"],
            }
            for traffic_name, aliases in traffic_aliases.items():
                if any(alias in input_lower for alias in aliases):
                    params["traffic_type"] = traffic_name
                    break

        if params["traffic_type"] and not params["ga4_channel"]:
            tt = params["traffic_type"].lower()
            traffic_to_channel = {
                "social": "Paid Social",
                "newsletter": "Email",
                "email": "Email",
                "paid search": "Paid Search",
                "display": "Display",
                "referral": "Referral",
            }
            if tt in traffic_to_channel:
                params["ga4_channel"] = traffic_to_channel[tt]

        if not params["ga4_channel"]:
            channel_keywords = {
                "organic social": "Organic Social",
                "paid social": "Paid Social",
                "email": "Email",
                "paid search": "Paid Search",
                "display": "Display",
                "referral": "Referral",
            }
            for kw, channel in channel_keywords.items():
                if kw in input_lower:
                    params["ga4_channel"] = channel
                    break

        if not params.get("campaign_country_language"):
            m_country_lang = re.search(r"\b([a-z]{2})(?:[-_ ]([a-z]{2}))\b", input_lower)
            if m_country_lang:
                params["campaign_country_language"] = f"{m_country_lang.group(1)}-{m_country_lang.group(2)}"
            else:
                m_country = re.search(r"\b(it|fr|de|es|uk|us|pt|nl|ch|at|be|pl)\b", input_lower)
                if m_country:
                    params["campaign_country_language"] = m_country.group(1)

        if not params.get("campaign_type"):
            type_aliases = {
                "promo": ["promo", "promozione", "promotional", "sale", "sconto", "saldi", "offerta", "lancio"],
                "ed": ["editoriale", "editorial", "blog", "contenuto", "content"],
                "tr": ["transactional", "transazionale", "conversion", "retargeting", "remarketing", "acquisto"],
                "awr": ["awareness", "brand", "notorieta", "visibilita", "consideration"],
            }
            for type_key, aliases in type_aliases.items():
                if any(alias in input_lower for alias in aliases):
                    params["campaign_type"] = type_key
                    break

        if not params.get("campaign_date"):
            date_matches = re.findall(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{2}[./-]\d{2}[./-]\d{2,4}\b|\b\d{8}\b", plain_input)
            for token in date_matches:
                fixed = _try_fix_date_to_ddmmyyyy(token) or (token if re.fullmatch(r"\d{8}", token) else None)
                if fixed:
                    params["campaign_date"] = fixed
                    break

        if not params.get("campaign_cta"):
            m_cta = re.search(r"\b(cta|image|banner|video|btn|button|hero)\b", input_lower)
            if m_cta:
                params["campaign_cta"] = _sanitize_utm_value(m_cta.group(1))

        if not params.get("campaign_name") and plain_input and not has_explicit_utm:
            stopwords = {
                "la", "il", "lo", "gli", "le", "un", "una", "dei", "delle", "per", "con", "del", "della", "di", "da",
                "su", "tra", "fra", "campaign", "campagna", "utm", "link", "newsletter", "social", "ads", "google",
                "meta", "facebook", "instagram", "linkedin", "tiktok", "email", "dem"
            }
            words = re.findall(r"[a-zA-Z0-9àèéìòù_-]+", input_lower)
            kept = []
            for w in words:
                token = _sanitize_utm_value(w)
                if not token or token.isdigit() or token in stopwords or len(token) < 3:
                    continue
                kept.append(token)
                if len(kept) >= 3:
                    break
            if kept:
                params["campaign_name"] = "-".join(kept)

        if not params.get("utm_campaign"):
            country_lang = params.get("campaign_country_language")
            campaign_type = params.get("campaign_type")
            campaign_name = params.get("campaign_name")
            campaign_date = params.get("campaign_date")
            campaign_cta = params.get("campaign_cta")
            if country_lang and campaign_type and campaign_name and campaign_date:
                parts = [country_lang, campaign_type, campaign_name, campaign_date]
                if campaign_cta:
                    parts.append(campaign_cta)
                params["utm_campaign"] = "_".join(parts)

        utm_patterns = {
            "utm_medium": r"(?:utm_?medium|medium)\s*[:=]\s*([a-z0-9_-]+)",
            "utm_source": r"(?:utm_?source|source)\s*[:=]\s*([a-z0-9_-]+)",
            "utm_campaign": r"(?:utm_?campaign|campaign)\s*[:=]\s*([a-z0-9_-]+)",
            "utm_content": r"(?:utm_?content|content)\s*[:=]\s*([a-z0-9_-]+)",
            "utm_term": r"(?:utm_?term|term)\s*[:=]\s*([a-z0-9_-]+)",
        }
        for param, pattern in utm_patterns.items():
            if not params.get(param):
                m = re.search(pattern, input_lower)
                if m:
                    params[param] = m.group(1)

        optional_step = str(context.get("optional_step") or "content")
        decline_optional = any(
            phrase in input_lower for phrase in [
                "nessuno", "nessuna", "niente", "no", "no grazie", "lascia vuoto",
                "vuoto", "non serve", "skip"
            ]
        )
        if params.get("utm_campaign") and optional_step == "content" and not params.get("utm_content"):
            if decline_optional:
                context["optional_step"] = "term"
            else:
                inferred_content = _infer_optional_value_from_text(plain_input)
                if inferred_content:
                    params["utm_content"] = inferred_content
                    context["optional_step"] = "term"

        optional_step = str(context.get("optional_step") or "content")
        if params.get("utm_campaign") and optional_step == "term" and not params.get("utm_term"):
            if decline_optional:
                context["optional_step"] = "done"
            else:
                inferred_term = _infer_optional_value_from_text(plain_input)
                if inferred_term:
                    params["utm_term"] = inferred_term
                    context["optional_step"] = "done"

        step_map = [
            "destination_url",   # step 1
            "campaign_brief",    # step 2
            "traffic_type",      # step 3
            "utm_medium",        # step 4
            "utm_source",        # step 5
            "utm_campaign",      # step 6
        ]
        filled = 0
        for param_name in step_map:
            if params.get(param_name):
                filled += 1
            else:
                break
        new_step = max(context["current_step"], filled)
        if filled >= 6:
            optional_step = str(context.get("optional_step") or "content")
            if optional_step == "done":
                new_step = max(new_step, 7)
            else:
                new_step = max(new_step, 6)
        context["current_step"] = new_step

    except Exception:
        pass


def _enforce_guided_single_question(raw_text: str, context: dict) -> str:
    """Evita risposte che chiedono tutti i token utm_campaign in blocco."""
    text = str(raw_text or "").strip()
    if not text:
        return text

    low = text.lower()
    asks_all_tokens = (
        ("country-lingua" in low or "country/lingua" in low or "country lingua" in low)
        and ("campaigntype" in low or "campaign type" in low)
        and ("campaignname" in low or "campaign name" in low)
        and ("data" in low or "date" in low)
    )
    looks_like_list = ("* country" in low or "* campaigntype" in low or "1) country" in low)

    if asks_all_tokens or looks_like_list:
        if not context["params"].get("campaign_brief"):
            return (
                "Perfetto, andiamo passo passo. "
                "Mi descrivi in 1-2 frasi la campagna (obiettivo, piattaforma e periodo)? "
                "Da questa descrizione ricavo io i parametri."
            )
        if not context["params"].get("campaign_name"):
            return "Ottimo. Qual e il nome interno della campagna che vuoi tracciare?"
        if not context["params"].get("campaign_date"):
            return "Perfetto. Qual e la data di riferimento della campagna? (accetto anche 2026-07-01)"
        return "Ricevuto. Ti propongo ora una bozza di utm_campaign e ti chiedo solo conferma finale."

    return text
def _build_system_instruction(
    context: dict,
    current_date: str,
    client_rules_text: str = "",
    preferred_property_id: str = "",
    preferred_property_name: str = "",
) -> str:
    """
    Builds the system instruction with static rules, skill guidelines,
    and dynamic conversation state.
    """
    def _val(key: str) -> str:
        v = context["params"].get(key)
        return v if v else "non ancora fornito"

    step_descriptions = {
        0: "Chiedi l'URL di destinazione (step 1)",
        1: "Chiedi una breve descrizione della campagna (1-2 frasi) e ricava automaticamente il più possibile",
        2: "Fai domande diagnostiche sul contesto traffico SOLO se non già noto",
        3: "Raccomanda utm_medium coerente col contesto e con le regole cliente",
        4: "Raccomanda utm_source coerente col contesto e con le regole cliente",
        5: "Costruisci utm_campaign chiedendo un solo token mancante per volta",
        6: "Chiedi parametri opzionali utm_content e utm_term",
        7: "Genera il link finale completo",
    }
    next_step = min(context["current_step"], 7)
    next_desc = step_descriptions.get(next_step, "Genera il link finale completo (step finale)")

    ga4_val = context.get("ga4_property_id") or "non ancora selezionata"
    client_rules_block = ""
    if client_rules_text:
        client_rules_block = f"""
REGOLE CLIENTE (PRIORITARIE)
- Applica queste regole specifiche del cliente prima dei mapping generici.
- Se ci sono conflitti tra regole generiche e regole cliente, vincono le regole cliente.
{client_rules_text}
"""
    property_preselection_block = ""
    preferred_pid = str(preferred_property_id or "").replace("properties/", "").strip()
    preferred_label = str(preferred_property_name or "").strip()
    if preferred_pid:
        chosen_label = preferred_label or f"properties/{preferred_pid}"
        property_preselection_block = f"""
PROPERTY CLIENTE PRESELEZIONATA (DEFAULT OPERATIVA)
- Property corrente selezionata nel Builder: {chosen_label} (properties/{preferred_pid}).
- NON chiedere all'utente di scegliere la property.
- Usa questa property come riferimento iniziale.
- Se l'utente indica chiaramente una country/property diversa, aggiorna il riferimento e prosegui senza bloccare.
- Se GA4 non è accessibile (permessi mancanti/errore), continua con le regole cliente da file UTM senza fermare il flusso.
"""

    base = f"""Sei WR Assistant, un esperto nella generazione di parametri UTM.
Oggi è il {current_date}.

OBIETTIVO
Guidare l'utente a creare un URL tracciato che:
- rispetti PRIMA DI TUTTO la naming convention del file UTM cliente configurato
- usi GA4 solo come controllo di coerenza/adozione, mai come fonte primaria di naming
- finisca nel canale corretto secondo il channel grouping PRIMARIO della property
{client_rules_block}
{property_preselection_block}

REGOLE VISIVE
1) Solo testo semplice (no HTML, no markdown complesso, no blocchi di codice).
2) UNA sola domanda per messaggio.
3) OUTPUT FINALE: stampa SOLO il link completo con un'istruzione del tipo "Copia e incolla questo link completo:".
   NON stampare JSON, NON usare parentesi graffe.
4) Rispondi esclusivamente in italiano corretto.
5) Non usare parole o caratteri di altre lingue/scritture.

REGOLE DI GUIDA CONSULENZIALE (OBBLIGATORIE)
- L'utente è inesperto: non dare per scontata la conoscenza di canali o UTM.
- NON chiedere mai: "in quale canale vuoi confluire?" o varianti simili.
- Devi dedurre il canale più corretto dalle informazioni raccolte (obiettivo, piattaforma, paid vs organic, formato annuncio, pubblico).
- Se mancano dati, fai domande diagnostiche specifiche e concrete (es. "La campagna parte da newsletter inviata dal CRM o da piattaforma adv?").
- Dopo ogni risposta utile, proponi tu la coppia consigliata canale + utm_medium + utm_source e chiedi solo conferma.
- Se GA4 è disponibile, usalo solo per verificare se i valori proposti sono già usati e in quale canale confluiscono; NON usarlo per decidere il naming.
- NON chiedere mai liste lunghe di campi (country, lingua, campaignType, campaignName, data, CTA) nello stesso messaggio.
- Prima chiedi sempre una descrizione breve della campagna e ricava automaticamente i campi possibili.
- Per utm_campaign chiedi un solo token mancante alla volta.
- Se le REGOLE CLIENTE elencano valori ammessi per utm_medium o utm_source, proponi solo valori presenti in quell'elenco.
- Non proporre mai alternative fuori elenco cliente solo perche semanticamente plausibili.
- Se per il caso corrente il file cliente rende disponibile un solo utm_medium coerente, proponi solo quello e chiedi conferma, senza alternative.
- Anche se utm_content e utm_term sono opzionali, devi sempre dedicarvi un passaggio prima del link finale.
- Per utm_content fai una domanda concreta, per esempio sul nome della CTA, del bottone, del banner, della hero o del visual principale.
- Per utm_term fai una domanda concreta su keyword, audience, segmento, promo, categoria o dettaglio utile, oppure chiedi se lasciarlo vuoto.

GERARCHIA DECISIONALE (VINCOLANTE)
1) REGOLE CLIENTE da file UTM configurato (fonte primaria e prioritaria).
2) Mapping generico interno SOLO se il file cliente non copre esplicitamente quel caso.
3) GA4 solo come check ex-post (coerenza canale / presenza storica), mai per scegliere i valori.
4) Se GA4 mostra valori storici in conflitto con le regole cliente, scarta i valori GA4 e mantieni le regole cliente.
5) Non proporre mai utm_source/utm_medium non previsti dalla convenzione cliente quando la convenzione li definisce.
6) Se le regole cliente contengono esempi o liste di valori consentiti, gli esempi generici non possono ampliare quell'insieme.

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

MAPPING utm_medium / utm_source (USARE SOLO COME FALLBACK SE LE REGOLE CLIENTE NON COPRONO IL CASO)
- Organic: medium=organic, source=google|bing|yahoo|yandex
- Referral: medium=referral, source=[website domain]
- Direct: medium=(none), source=(direct)
- Paid campaign: medium=cpc, source=google|bing
- Affiliate: medium=affiliate, source=tradetracker
- Display: medium=cpm, source=reservation|display|programmatic_video
- Video: medium=cpv, source=youtube
- Programmatic: medium=cpm, source=rcs|mediamond|rai|ilsole24ore
- Email/Newsletter: medium=email, source=newsletter|email|crm
- Social organic: medium=social_org, source=facebook|instagram|linkedin|...(nome social)
- Social paid: medium=social_paid, source=facebook|instagram|linkedin|...(nome social)
- App traffic: medium=(chiedere all'utente), source=app
- Offline: medium=offline, source=brochure|qr_code|sms

 REGOLE utm_campaign
 - Se le REGOLE CLIENTE definiscono una struttura esplicita per utm_campaign, usa ESATTAMENTE quella struttura.
 - Se le REGOLE CLIENTE mostrano esempi di utm_campaign, trattali come riferimento prioritario per ordine, numero e significato dei token.
 - Non trasformare mai un token iniziale previsto dal cliente (es. brandcountry) in country o country-lingua.
 - Il formato seguente vale SOLO come fallback se il file cliente non definisce una struttura esplicita.
 Formato fallback: country-lingua_campaignType_campaignName_data[_CTA]
 Token separati da underscore _, parole dentro un token separate da trattino -.
 Token fallback richiesti:
 1) country-lingua: indica la provenienza/lingua della campagna. È sufficiente inserire UNO dei due: solo il paese (es. it, ch, es) OPPURE paese-lingua (es. it-it, ch-de, es-es). Non è obbligatorio fornire entrambi. Esempi validi: "it", "ch", "it-it", "ch-de".
 2) campaignType: preferibilmente promo (promotional), ed (editorial), tr (transactional), awr (awareness); sono consentiti anche nuovi tipi personalizzati
 3) campaignName: nome interno della campagna
 4) data: data invio/riferimento temporale (formato GGMMAAAA, senza separatori)
 Token fallback opzionale:
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
- Non usare GA4 per scegliere il naming.
- Usalo quando:
  a) l'utente chiede verifica/storico (es. "ultimo anno")
  b) vuoi verificare se la proposta conforme al file cliente è già stata usata
  c) vuoi controllare in quale canale GA4 finirebbe la proposta
- Se in GA4 esistono source/medium "sporchi" o errati, NON riutilizzarli.

GESTIONE ERRORI GA4
- Se un tool GA4 restituisce un dict con chiave "error", riporta all'utente il messaggio esatto: es. "Errore GA4: <valore di error>".
- Se l'errore contiene "error_type", segnalalo: es. "Tipo: PermissionDenied".
- Non assumere che sia sempre un problema di permessi: potrebbe essere un token scaduto, uno scope mancante, o un property_id errato.
- Se GA4 non è disponibile, continua comunque il flusso UTM usando le regole statiche e i mapping definiti sopra.
- Non bloccare il flusso UTM a causa di errori GA4: prosegui e proponi opzioni basate sulle regole.

PROPERTY GA4: AUTO-SELEZIONE SENZA CONFERMA
- Quando hai un URL di destinazione, usa tool_guess_property_from_url(URL) e seleziona automaticamente la migliore candidata (score più alto).
- NON chiedere conferma della property all'utente.
- Se non trovi candidate affidabili, continua con regole statiche senza bloccare il flusso.

FLOW (UNA DOMANDA PER STEP, ADATTIVO)
STEP 1: URL destinazione (normalizza a https://www.)
STEP 2: Richiedi una breve descrizione libera della campagna (1-2 frasi)
- Da quella descrizione inferisci automaticamente: traffic_type, canale, country-lingua, campaignType, campaignName, data (se presenti)
STEP 3: Diagnosi del contesto traffico SOLO se non già noto
- Domande specifiche: piattaforma, paid vs organic, tipo campagna (newsletter/social/search/display/altro)
STEP 4: utm_medium (raccomandato dal bot, non chiesto in modo generico)
- Proponi 1 opzione consigliata + 1 alternativa coerente col contesto
- Le opzioni devono rispettare prima il file UTM cliente; usa mapping generico solo come fallback
- Se il file cliente prevede un solo medium coerente con il caso, proponi solo quel medium e nessuna alternativa
- Se fai check GA4, usalo solo per segnalare adozione/coerenza canale, non per scegliere i valori
STEP 5: utm_source (raccomandato dal bot)
- Proponi 1 opzione consigliata + 1 alternativa coerente col contesto
- Le opzioni devono rispettare prima il file UTM cliente; usa mapping generico solo come fallback
- Se il file cliente prevede una sola source coerente con il caso, proponi solo quella e nessuna alternativa
- Se fai check GA4, usalo solo per segnalare adozione/coerenza canale, non per scegliere i valori
STEP 6: utm_campaign
- NON chiedere mai tutti i token insieme.
- Se le REGOLE CLIENTE definiscono i token o il loro ordine, segui quell'ordine e quella semantica.
- Chiedi un solo token mancante per volta.
- Solo se il file cliente non definisce i token, usa questo fallback:
  1) country-lingua, 2) campaignType, 3) campaignName, 4) data, 5) CTA (opzionale)
- Se i token sono già deducibili dalla descrizione, proponi direttamente una bozza e chiedi solo conferma.
STEP 7: utm_content
- Anche se opzionale, chiedilo sempre prima del link finale.
- Fai una domanda concreta sul contenuto creativo, per esempio CTA, bottone, banner, hero, visual o placement.
- Se l'utente non vuole valorizzarlo, accetta una risposta come "lascialo vuoto" e passa oltre.
STEP 8: utm_term
- Anche se opzionale, chiedilo sempre dopo utm_content e prima del link finale.
- Fai una domanda concreta su keyword, audience, segmento, promo, categoria o dettaglio utile.
- Se l'utente non vuole valorizzarlo, accetta una risposta come "lascialo vuoto" e passa oltre.
STEP 9: output finale SOLO LINK (con query correttamente formattata e senza caratteri speciali nei valori UTM).

STATO ATTUALE DELLA CONVERSAZIONE
- Step attuale: {next_step} di 9
- Parametri raccolti:
  - URL destinazione: {_val("destination_url")}
  - Descrizione campagna: {_val("campaign_brief")}
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
- Se l'utente dice "campagna social", NON chiedere se è email/display: proponi direttamente opzioni social coerenti.
- Se l'utente dice "newsletter/email/DEM", proponi direttamente canale Email con medium/source coerenti e chiedi solo conferma.
- Prima di proporre source/medium, controlla sempre le REGOLE CLIENTE e usa esattamente quei valori quando presenti.
- Se nelle REGOLE CLIENTE per email compare solo utm_medium=email, non nominare mailing_campaign.
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
def render_chatbot_interface(
    creds,
    api_key_func=None,
    history_save_func=None,
    client_rules_text: str = "",
    preferred_property_id: str = "",
    preferred_property_name: str = "",
) -> None:
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
    if "chat_welcome_sent" not in st.session_state:
        st.session_state.chat_welcome_sent = False
    if "utm_context" not in st.session_state:
        st.session_state.utm_context = {
            "current_step": 0,
            "optional_step": "content",
            "params": {
                "destination_url": None,
                "campaign_brief": None,
                "traffic_type": None,
                "ga4_channel": None,
                "utm_medium": None,
                "utm_source": None,
                "utm_campaign": None,
                "utm_content": None,
                "utm_term": None,
                "campaign_country_language": None,
                "campaign_type": None,
                "campaign_name": None,
                "campaign_date": None,
                "campaign_cta": None,
            },
            "ga4_property_id": None,
            "tool_cache": {},
        }
    # Backward compatibility: allinea eventuali sessioni vecchie ai nuovi campi.
    st.session_state.utm_context.setdefault("current_step", 0)
    st.session_state.utm_context.setdefault("optional_step", "content")
    st.session_state.utm_context.setdefault("ga4_property_id", None)
    st.session_state.utm_context.setdefault("tool_cache", {})
    st.session_state.utm_context.setdefault("params", {})
    for _k in [
        "destination_url", "campaign_brief", "traffic_type", "ga4_channel",
        "utm_medium", "utm_source", "utm_campaign", "utm_content", "utm_term",
        "campaign_country_language", "campaign_type", "campaign_name", "campaign_date", "campaign_cta",
    ]:
        st.session_state.utm_context["params"].setdefault(_k, None)
    current_profile_signature = hashlib.sha256(
        f"{client_rules_text}|{preferred_property_id}|{preferred_property_name}".encode("utf-8")
    ).hexdigest()
    prev_profile_signature = str(st.session_state.get("chat_profile_signature", "")).strip()
    if prev_profile_signature and prev_profile_signature != current_profile_signature:
        st.session_state.messages = []
        st.session_state.chat_welcome_sent = False
        st.session_state.chat_is_responding = False
        st.session_state.pending_user_text = None
        st.session_state.utm_context = {
            "current_step": 0,
            "optional_step": "content",
            "params": {
                "destination_url": None,
                "campaign_brief": None,
                "traffic_type": None,
                "ga4_channel": None,
                "utm_medium": None,
                "utm_source": None,
                "utm_campaign": None,
                "utm_content": None,
                "utm_term": None,
                "campaign_country_language": None,
                "campaign_type": None,
                "campaign_name": None,
                "campaign_date": None,
                "campaign_cta": None,
            },
            "ga4_property_id": None,
            "tool_cache": {},
        }
        st.session_state.chat_sync_notice = "Chat riallineata automaticamente all'ultima configurazione UTM del cliente."
    st.session_state.chat_profile_signature = current_profile_signature
    preferred_pid_ctx = str(preferred_property_id or "").replace("properties/", "").strip()
    if preferred_pid_ctx:
        st.session_state.utm_context["ga4_property_id"] = preferred_pid_ctx

    def _queue_user_message(text: str) -> None:
        clean_text = (text or "").strip()
        if not clean_text or st.session_state.chat_is_responding:
            return
        st.session_state.messages.append({"role": "user", "content": clean_text})
        st.session_state.pending_user_text = clean_text
        st.session_state.chat_is_responding = True
        st.rerun()

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
            width: 56px !important;
            height: 56px !important;
            border-radius: 50% !important;
            border: 2px solid #5cb99e !important;
            box-shadow: 0 6px 24px rgba(26, 35, 50, 0.25) !important;
            transition: transform 0.2s, box-shadow 0.2s !important;
            background: #1a2332 !important;
            display: block !important;
            margin: 0 !important;
            color: transparent !important;
        }}
        
        div[data-testid="stColumn"]:has(div.fab-unique-marker) button:hover {{
            transform: scale(1.08);
            box-shadow: 0 8px 32px rgba(92, 185, 158, 0.3) !important;
        }}
        
        div[data-testid="stColumn"]:has(div.fab-unique-marker) button p {{
            display: none !important;
        }}
        div[data-testid="stColumn"]:has(div.fab-unique-marker) button::after {{
            content: "\\1F4AC";
            font-size: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100%;
            color: #5cb99e;
        }}
        
        /* Nasconde il marker stesso */
        .fab-unique-marker {{
            display: none;
        }}
    """
    # 2. STYLE PER LA WINDOW
    window_css = """
        @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=Manrope:wght@500;600;700&display=swap');

        :root {
            --chat-ink: #142132;
            --chat-muted: #4f637b;
            --chat-line: #d2deeb;
            --chat-aqua: #67cdb7;
            --chat-aqua-strong: #49b49b;
            --chat-panel: #f7fbff;
        }

        /* ------------------------------------------------
         * CHAT WINDOW: fixed overlay, non disturba il layout
         * Il selector prende il vertical block piu' interno
         * con marker dedicato per evitare side effect sui parent.
         * ------------------------------------------------ */
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope)) {
            position: fixed;
            bottom: 110px;
            right: 30px;
            width: 604px !important;
            max-width: 90vw;
            height: auto !important;
            max-height: 85vh;
            background:
                radial-gradient(680px 200px at -12% -12%, rgba(103, 205, 183, 0.22), transparent 50%),
                linear-gradient(180deg, #ffffff 0%, #f7fbff 100%);
            border-radius: 22px;
            box-shadow: 0 30px 95px rgba(15, 30, 49, 0.24), 0 8px 24px rgba(0, 0, 0, 0.1);
            z-index: 999998;
            border: 1px solid var(--chat-line);
            overflow: hidden;
            display: flex;
            flex-direction: column;
            padding: 0 !important;
            gap: 0 !important;
            animation: chat-window-rise .22s ease-out;
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
            height: auto;
            max-height: 390px;
            min-height: 0;
            overflow-y: auto;
            scroll-behavior: smooth;
            padding: 22px 18px 18px 18px;
            display: flex;
            flex-direction: column;
            gap: 11px;
            background:
                radial-gradient(circle at 100% 0%, rgba(103, 205, 183, 0.18), rgba(103, 205, 183, 0) 44%),
                linear-gradient(180deg, #ffffff 0%, #f7fbff 100%);
            flex: 0 0 auto;
            overflow-anchor: none;
        }
        .chat-messages-area.chat-messages-fresh {
            min-height: 250px;
            padding-bottom: 70px;
        }

        /* Input area dentro la window */
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            > div[data-testid="element-container"]:has(div[data-testid="stForm"]) {
            margin-top: auto !important;
            margin-bottom: 0 !important;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="stVerticalBlock"]:has(.chat-quick-panel-marker) {
            margin: 8px 14px 14px 14px !important;
            padding: 8px 12px 10px 12px !important;
            border-radius: 18px !important;
            background: linear-gradient(180deg, rgba(255, 255, 255, 0.9) 0%, rgba(243, 249, 255, 0.96) 100%) !important;
            border: 1px solid rgba(205, 220, 235, 0.9) !important;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.72), 0 8px 18px rgba(18, 34, 52, 0.06) !important;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="element-container"]:has(.chat-quick-group-marker) {
            margin-top: 4px !important;
            margin-bottom: 8px !important;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="element-container"]:has(.chat-input-group-marker) {
            margin-top: 18px !important;
            margin-bottom: 0 !important;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="stForm"] {
            padding: 28px 14px 14px !important;
            border-top: 1px solid var(--chat-line);
            background:
                linear-gradient(180deg, rgba(255, 255, 255, 0.64) 0%, rgba(241, 248, 255, 0.95) 100%);
            backdrop-filter: blur(5px);
            position: sticky;
            bottom: 0;
            z-index: 3;
            margin-bottom: 0 !important;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="stForm"] form {
            margin-bottom: 0 !important;
            padding-bottom: 0 !important;
            margin-top: 6px !important;
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
            background:
                radial-gradient(300px 140px at 100% 0%, rgba(103, 205, 183, 0.28), transparent 56%),
                linear-gradient(132deg, #0f1d30 0%, #1a3048 58%, #154453 100%);
            color: #ffffff;
            padding: 16px 18px 16px 18px;
            display: flex;
            align-items: center;
            gap: 12px;
            font-family: "Manrope", "Segoe UI", sans-serif;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            flex-shrink: 0;
            line-height: 1.2;
        }
        .chat-header-logo {
            width: 36px;
            height: 36px;
            border-radius: 11px;
            background: linear-gradient(145deg, #93e3cf, #66cdb8);
            color: #103840;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-weight: 800;
            font-family: "Fraunces", serif;
            font-size: 22px;
            line-height: 1;
            box-shadow: 0 8px 18px rgba(103, 205, 183, 0.38);
        }
        .chat-header-text {
            display: flex;
            flex-direction: column;
            gap: 2px;
        }
        .chat-header-title {
            font-family: "Fraunces", serif;
            font-size: 19px;
            font-weight: 700;
            letter-spacing: 0.02em;
            color: #f4f8ff;
        }
        .chat-header-sub {
            font-size: 12px;
            color: rgba(223, 237, 255, 0.88);
            font-weight: 600;
        }
        .debug-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            font-size: 11px;
            color: #1e3a8a;
            background: #dbeafe;
            border: 1px solid #bfdbfe;
            border-radius: 999px;
            padding: 4px 8px;
            margin: 4px 8px 8px 8px;
            width: fit-content;
        }

        .msg-bubble {
            padding: 12px 15px;
            border-radius: 16px;
            font-size: 13px;
            line-height: 1.58;
            max-width: 85%;
            word-wrap: break-word;
            font-family: "Manrope", "Segoe UI", sans-serif;
            box-shadow: 0 6px 16px rgba(16, 30, 46, 0.09);
        }
        .msg-user {
            background: linear-gradient(145deg, #162842, #27496f);
            color: #ffffff;
            align-self: flex-end;
            border-radius: 16px 4px 16px 16px;
        }
        .msg-bot {
            background: linear-gradient(180deg, #eef8f3 0%, #e7f4ee 100%);
            color: #193447;
            border: 1px solid #d3eadf;
            align-self: flex-start;
            border-radius: 4px 16px 16px 16px;
        }
        .msg-bot.copy-ready {
            min-width: min(520px, 85%);
        }
        .msg-copy-actions {
            display: flex;
            justify-content: flex-end;
            margin-top: 10px;
        }
        .msg-copy-btn {
            border: 1px solid #a7cdbf;
            background: #ffffff;
            color: #1d4b45;
            border-radius: 999px;
            padding: 7px 12px;
            font-size: 12px;
            font-weight: 700;
            font-family: "Manrope", "Segoe UI", sans-serif;
            cursor: pointer;
            transition: all .18s ease;
            box-shadow: 0 2px 8px rgba(28, 68, 64, 0.08);
        }
        .msg-copy-btn:hover {
            background: #f4fbf8;
            border-color: #79b9aa;
        }
        .msg-copy-btn.copied {
            background: #dff5eb;
            border-color: #7dc3aa;
            color: #175743;
        }
        .msg-row-bot {
            display: flex;
            justify-content: flex-start;
            margin-bottom: 2px;
            gap: 12px;
            align-items: flex-start;
        }
        .msg-row-user {
            display: flex;
            justify-content: flex-end;
            margin-bottom: 8px;
        }
        .bot-avatar {
            width: 36px;
            height: 36px;
            border-radius: 999px;
            border: 2px solid #ffffff;
            background: linear-gradient(145deg, #8fe1cb, #67ceb8);
            color: #11414a;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-family: "Fraunces", serif;
            font-weight: 700;
            font-size: 20px;
            flex-shrink: 0;
            box-shadow: 0 7px 14px rgba(103, 205, 183, 0.26);
        }
        .msg-loading {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            color: hsl(224, 64%, 10%);
            background: #d4f0e5;
            border-color: #5cb99e;
        }
        .chat-loader {
            width: 14px;
            height: 14px;
            border-radius: 50%;
            border: 2px solid rgba(102, 198, 172, 0.35);
            border-top-color: hsl(163, 40%, 60%);
            animation: chat-loader-spin .8s linear infinite;
            flex-shrink: 0;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="stTextInput"] input {
            border: 1px solid #d1dde8 !important;
            border-radius: 15px !important;
            background: #ffffff !important;
            color: var(--chat-ink) !important;
            font-family: "Manrope", "Segoe UI", sans-serif !important;
            min-height: 50px !important;
            font-size: 14px !important;
            padding: 12px 16px !important;
            outline: none !important;
            box-shadow: 0 3px 8px rgba(20, 36, 52, 0.06) !important;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="stTextInput"] div[data-baseweb="input"] {
            border: 1px solid #dbe5ef !important;
            border-radius: 15px !important;
            box-shadow: none !important;
            background: #ffffff !important;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="stTextInput"] input:focus {
            border-color: var(--chat-aqua-strong) !important;
            outline: none !important;
            box-shadow: 0 0 0 3px rgba(103, 205, 183, 0.2) !important;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="stTextInput"] div[data-baseweb="input"]:focus-within {
            border-color: var(--chat-aqua-strong) !important;
            box-shadow: 0 0 0 3px rgba(103, 205, 183, 0.2) !important;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="stTextInput"] input:invalid,
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="stTextInput"] input[aria-invalid="true"],
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="stTextInput"] div[data-baseweb="input"][aria-invalid="true"] {
            border-color: #e9edf2 !important;
            box-shadow: none !important;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="stForm"] [data-testid="InputInstructions"],
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="stForm"] [data-testid="stFormSubmitInstructions"] {
            display: none !important;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="stFormSubmitButton"] button {
            border-radius: 13px !important;
            border: none !important;
            background: linear-gradient(145deg, #58bf9f, #45a687) !important;
            color: #ffffff !important;
            min-height: 48px !important;
            width: 100% !important;
            font-weight: 700 !important;
            font-size: 18px !important;
            line-height: 1.1 !important;
            font-family: "Manrope", "Segoe UI", sans-serif !important;
            letter-spacing: 0.01em !important;
            padding: 0 16px !important;
            box-shadow: 0 9px 18px rgba(74, 168, 138, 0.24) !important;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="stFormSubmitButton"] button:hover {
            background: linear-gradient(145deg, #4eb090, #3d987d) !important;
            transform: translateY(-1px) !important;
            box-shadow: 0 10px 18px rgba(74, 168, 138, 0.28) !important;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="stButton"] button {
            border-radius: 999px !important;
            border: 1px solid #cad9e7 !important;
            background: linear-gradient(180deg, #ffffff 0%, #f6fbff 100%) !important;
            color: #1f3a53 !important;
            font-family: "Manrope", "Segoe UI", sans-serif !important;
            font-weight: 600 !important;
            min-height: 40px !important;
            height: 40px !important;
            width: 100% !important;
            font-size: 13px !important;
            padding: 6px 14px !important;
            white-space: nowrap !important;
            box-shadow: 0 3px 8px rgba(20, 36, 52, 0.09);
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="stButton"] button:hover {
            background: #edf7ff !important;
            border-color: #acc7df !important;
            transform: translateY(-1px) !important;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="element-container"]:has(.chat-quick-marker) {
            margin-top: 18px !important;
            margin-bottom: 14px !important;
        }
        .chat-quick-marker {
            display: none;
        }
        .chat-quick-panel-marker {
            display: none;
        }
        .chat-quick-group-marker {
            display: none;
        }
        .chat-quick-spacer {
            display: block;
            height: 6px;
            width: 100%;
        }
        .chat-input-group-marker {
            display: none;
        }
        .chat-input-spacer {
            display: block;
            height: 16px;
            width: 100%;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="element-container"]:has(.chat-messages-area) {
            margin-bottom: 6px !important;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="element-container"]:has(div[data-testid="stButton"]) {
            margin-top: 0 !important;
            margin-bottom: 0 !important;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="stVerticalBlock"]:has(.chat-quick-panel-marker) [data-testid="stHorizontalBlock"] {
            justify-content: center !important;
            gap: 12px !important;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="stVerticalBlock"]:has(.chat-quick-panel-marker) [data-testid="column"] {
            flex: 0 0 auto !important;
            width: auto !important;
            min-width: 0 !important;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="element-container"]:has(.chat-quick-spacer) {
            margin-top: 0 !important;
            margin-bottom: 0 !important;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="element-container"]:has(.chat-input-spacer) {
            margin-top: 0 !important;
            margin-bottom: 0 !important;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="element-container"]:has(.chat-input-marker) {
            margin-top: 24px !important;
            margin-bottom: 0 !important;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="stForm"] div[data-testid="stTextInput"] {
            margin-bottom: 0 !important;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="stForm"] div[data-testid="column"] {
            align-items: center !important;
        }
        div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
            div[data-testid="stForm"] div[data-testid="stTextInput"] > label {
            margin-bottom: 0 !important;
        }
        @media (max-width: 768px) {
            div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope)) {
                right: 12px;
                left: 12px;
                bottom: 86px;
                width: auto !important;
                max-width: none !important;
                border-radius: 14px;
                max-height: 80vh;
            }
            .chat-header {
                padding: 14px 14px;
            }
            .chat-header-title {
                font-size: 17px;
            }
            .chat-header-sub {
                font-size: 11px;
            }
            .chat-messages-area {
                padding: 16px 12px 14px 12px;
                max-height: 46vh;
            }
            .chat-messages-area.chat-messages-fresh {
                min-height: 210px;
                padding-bottom: 44px;
            }
            .msg-bubble {
                max-width: 90%;
                font-size: 12px;
            }
            div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
                div[data-testid="stButton"] button {
                min-height: 38px !important;
                height: 38px !important;
                font-size: 12px !important;
            }
            div[data-testid="stVerticalBlock"]:has(div.chat-window-scope):not(:has(div[data-testid="stVerticalBlock"] div.chat-window-scope))
                div[data-testid="stVerticalBlock"]:has(.chat-quick-panel-marker) {
                margin: 8px 10px 12px 10px !important;
                padding: 8px 10px 10px 10px !important;
                border-radius: 16px !important;
            }
            .chat-quick-spacer {
                height: 4px;
            }
            .chat-input-spacer {
                height: 12px;
            }
        }
        @keyframes chat-loader-spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }
        @keyframes chat-window-rise {
            from { opacity: 0; transform: translateY(10px) scale(0.99); }
            to { opacity: 1; transform: translateY(0) scale(1); }
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
        sync_notice = st.session_state.pop("chat_sync_notice", "")
        if sync_notice:
            st.info(sync_notice)
        # Messaggio di benvenuto persistente alla prima apertura chat
        if not st.session_state.chat_welcome_sent and not st.session_state.messages:
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": "Ciao! Sono l'assistente Smart UTM. Inizia descrivendomi in 1-2 frasi la campagna e ricavo io i parametri passo passo."
                }
            )
            st.session_state.chat_welcome_sent = True
        with st.container():
            st.markdown('<div class="chat-window-scope" style="display:none;"></div>', unsafe_allow_html=True)
            st.markdown(
                '<div class="chat-header"><span class="chat-header-logo">W</span><span class="chat-header-text"><span class="chat-header-title">Smart UTM Assistant</span><span class="chat-header-sub">Percorso guidato per creare URL UTM coerenti e puliti</span></span></div>',
                unsafe_allow_html=True,
            )

            # MESSAGES - render come HTML puro per evitare spazio nel layout Streamlit
            has_user_messages = any(m.get("role") == "user" for m in st.session_state.messages)
            fresh_chat = not has_user_messages
            messages_area_class = "chat-messages-area chat-messages-fresh" if fresh_chat else "chat-messages-area"
            if not st.session_state.messages and not st.session_state.chat_is_responding:
                msgs_html = (
                    f'<div class="{messages_area_class}" role="log" aria-live="polite" aria-atomic="false">'
                    '<div class="msg-row-bot"><span class="bot-avatar">W</span><div class="msg-bubble msg-bot">'
                    "Ciao! Sono l'assistente Smart UTM. Inizia descrivendomi in 1-2 frasi la campagna e ricavo io i parametri passo passo."
                    "</div></div></div>"
                )
            else:
                rows = []
                if st.session_state.chat_is_responding:
                    rows.append(
                        '<div class="msg-row-bot"><span class="bot-avatar">W</span>'
                        '<div class="msg-bubble msg-bot msg-loading"><span class="chat-loader"></span>'
                        'Smart UTM Assistant sta rispondendo...</div></div>'
                    )

                for msg in st.session_state.messages:
                    raw_content = str(msg.get("content", ""))
                    content = html_lib.escape(raw_content).replace("\n", "<br>")
                    if msg["role"] == "user":
                        rows.append(f'<div class="msg-row-user"><div class="msg-bubble msg-user">{content}</div></div>')
                    else:
                        final_url = ""
                        if "Copia e incolla questo link completo:" in raw_content and "utm_" in raw_content:
                            final_url = _extract_first_url(raw_content) or ""
                        if final_url:
                            safe_url_attr = html_lib.escape(final_url, quote=True)
                            rows.append(
                                '<div class="msg-row-bot"><span class="bot-avatar">W</span>'
                                f'<div class="msg-bubble msg-bot copy-ready">{content}'
                                '<div class="msg-copy-actions">'
                                f'<button class="msg-copy-btn" type="button" data-copy-url="{safe_url_attr}">Copia</button>'
                                '</div></div></div>'
                            )
                        else:
                            rows.append(f'<div class="msg-row-bot"><span class="bot-avatar">W</span><div class="msg-bubble msg-bot">{content}</div></div>')

                msgs_html = f'<div class="{messages_area_class}" role="log" aria-live="polite" aria-atomic="false">' + ''.join(rows) + '</div>'
            st.markdown(msgs_html, unsafe_allow_html=True)
            components.html(
                """
                <script>
                (function () {
                  const doc = window.parent && window.parent.document ? window.parent.document : document;
                  const getArea = () => {
                    const marker = doc.querySelector('.chat-window-scope');
                    if (!marker) return null;
                    const scope = marker.closest('div[data-testid="stVerticalBlock"]');
                    if (!scope) return null;
                    return scope.querySelector('.chat-messages-area');
                  };
                  const scrollToBottom = (area) => {
                    if (!area) return;
                    area.scrollTo({ top: area.scrollHeight, behavior: 'smooth' });
                  };
                  let tries = 0;
                  const timer = setInterval(() => {
                    const area = getArea();
                    if (!area) {
                      tries += 1;
                      if (tries > 50) clearInterval(timer);
                      return;
                    }
                    clearInterval(timer);
                    scrollToBottom(area);
                    setTimeout(() => scrollToBottom(area), 80);
                    setTimeout(() => scrollToBottom(area), 220);

                    if (!area.dataset.wrAutoScrollBound) {
                      const observer = new MutationObserver(() => scrollToBottom(area));
                      observer.observe(area, { childList: true, subtree: true, characterData: true });
                      area.dataset.wrAutoScrollBound = '1';
                      window.addEventListener('resize', () => scrollToBottom(area), { passive: true });
                    }
                  }, 50);

                  const copyText = async (value) => {
                    const parentWindow = doc.defaultView || window.parent || window;
                    try {
                      if (parentWindow.navigator && parentWindow.navigator.clipboard && parentWindow.isSecureContext) {
                        await parentWindow.navigator.clipboard.writeText(value);
                        return true;
                      }
                    } catch (err) {}

                    try {
                      const textarea = doc.createElement('textarea');
                      textarea.value = value;
                      textarea.setAttribute('readonly', '');
                      textarea.style.position = 'fixed';
                      textarea.style.top = '-1000px';
                      textarea.style.left = '-1000px';
                      textarea.style.opacity = '0';
                      doc.body.appendChild(textarea);
                      textarea.focus();
                      textarea.select();
                      textarea.setSelectionRange(0, textarea.value.length);
                      const successful = doc.execCommand('copy');
                      doc.body.removeChild(textarea);
                      return Boolean(successful);
                    } catch (err) {
                      return false;
                    }
                  };

                  if (!doc.body.dataset.wrCopyBound) {
                    doc.addEventListener('click', async (event) => {
                      const btn = event.target.closest('.msg-copy-btn');
                      if (!btn) return;
                      const url = btn.getAttribute('data-copy-url') || '';
                      if (!url) return;
                      try {
                        const copied = await copyText(url);
                        if (!copied) throw new Error('copy failed');
                        const oldText = btn.textContent;
                        btn.textContent = 'Copiato';
                        btn.classList.add('copied');
                        setTimeout(() => {
                          btn.textContent = oldText;
                          btn.classList.remove('copied');
                        }, 1400);
                      } catch (err) {
                        btn.textContent = 'Copia fallita';
                        setTimeout(() => {
                          btn.textContent = 'Copia';
                        }, 1600);
                      }
                    });
                    doc.body.dataset.wrCopyBound = '1';
                  }
                })();
                </script>
                """,
                height=0,
                width=0,
            )

            # INPUT
            chat_locked = bool(st.session_state.chat_is_responding)
            input_placeholder = "Smart UTM Assistant sta rispondendo..." if chat_locked else "Scrivi un messaggio..."

            st.markdown('<div class="chat-input-group-marker"></div>', unsafe_allow_html=True)
            st.markdown('<div class="chat-input-spacer"></div>', unsafe_allow_html=True)
            st.markdown('<div class="chat-input-marker"></div>', unsafe_allow_html=True)
            with st.form("chat_input_form", clear_on_submit=True):
                input_col, send_col = st.columns([0.8, 0.2], gap="small")
                with input_col:
                    user_text = st.text_input(
                        "Messaggio",
                        label_visibility="collapsed",
                        placeholder=input_placeholder,
                        disabled=chat_locked,
                    )
                with send_col:
                    submitted = st.form_submit_button("Invia", use_container_width=True, disabled=chat_locked)

            if submitted and user_text and not chat_locked:
                _queue_user_message(user_text)
            if st.session_state.chat_is_responding and st.session_state.pending_user_text:
                pending_text = st.session_state.pending_user_text

                try:
                    with st.spinner("Smart UTM Assistant sta rispondendo..."):
                        api_key = st.session_state.get("gemini_api_key")
                        if not api_key:
                            st.session_state.messages.append(
                                {"role": "assistant", "content": "Configura prima la API Key nelle impostazioni."}
                            )
                        else:
                            genai.configure(api_key=api_key)
                            utm_ctx = st.session_state.utm_context
                            # Aggiorna subito il contesto col testo utente corrente
                            # (cosi' destination_url e altri campi sono disponibili
                            # prima dell'auto-selezione property GA4).
                            _update_context_from_response("", pending_text, utm_ctx)

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
                                        ps = acc.get("propertySummaries") or acc.get("properties") or []
                                        if isinstance(ps, list):
                                            props.extend(ps)

                                candidates = []
                                for p in props:
                                    display = (
                                        p.get("displayName")
                                        or p.get("display_name")
                                        or p.get("name")
                                        or ""
                                    ).lower()
                                    pid = ""
                                    pid_raw = str(p.get("name") or p.get("property_id") or "")
                                    m = re.search(r"properties/(\d+)", pid_raw)
                                    if m:
                                        pid = m.group(1)
                                    elif re.fullmatch(r"\d+", pid_raw.strip()):
                                        pid = pid_raw.strip()
                                    score = 0
                                    if host_root and host_root in display:
                                        score += 3
                                    candidates.append(
                                        {
                                            "property_id": pid,
                                            "display_name": p.get("displayName") or p.get("display_name"),
                                            "score": score,
                                        }
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

                            # Auto-select GA4 property from destination URL without asking user confirmation
                            try:
                                dest_url = utm_ctx["params"].get("destination_url")
                                if dest_url and not utm_ctx.get("ga4_property_id"):
                                    guessed = tool_guess_property_from_url(dest_url)
                                    candidates = guessed.get("candidates", []) if isinstance(guessed, dict) else []
                                    if candidates:
                                        best = sorted(
                                            candidates,
                                            key=lambda x: (x.get("score", 0), bool(x.get("property_id"))),
                                            reverse=True
                                        )[0]
                                        best_pid = best.get("property_id")
                                        if best_pid:
                                            utm_ctx["ga4_property_id"] = best_pid
                            except Exception:
                                pass

                            # --- Dynamic system instruction ---
                            current_date = datetime.now().strftime("%Y-%m-%d")
                            system_instruction = _build_system_instruction(
                                utm_ctx,
                                current_date,
                                client_rules_text=client_rules_text,
                                preferred_property_id=preferred_property_id,
                                preferred_property_name=preferred_property_name,
                            )

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
                            cleaned = _enforce_guided_single_question(cleaned, utm_ctx)
                            cleaned = _enforce_client_rule_options(cleaned, utm_ctx, client_rules_text)
                            cleaned = _enforce_optional_followup(cleaned, utm_ctx)

                            st.session_state.messages.append(
                                {
                                    "role": "assistant",
                                    "content": cleaned,
                                    "raw_content": response_text,
                                }
                            )

                            # Update conversation context
                            _update_context_from_response(response_text, pending_text, utm_ctx)

                            # Salva automaticamente nello storico UTM, se disponibile un link finale.
                            if callable(history_save_func):
                                try:
                                    final_url = _extract_first_url(cleaned or "")
                                    if final_url and "utm_" in final_url:
                                        # Retry auto-selezione property se ancora mancante
                                        # usando prima URL di destinazione, poi URL finale.
                                        if not utm_ctx.get("ga4_property_id"):
                                            try:
                                                guess_url = utm_ctx["params"].get("destination_url") or final_url
                                                guessed = tool_guess_property_from_url(guess_url)
                                                candidates = guessed.get("candidates", []) if isinstance(guessed, dict) else []
                                                if candidates:
                                                    best = sorted(
                                                        candidates,
                                                        key=lambda x: (x.get("score", 0), bool(x.get("property_id"))),
                                                        reverse=True
                                                    )[0]
                                                    best_pid = best.get("property_id")
                                                    if best_pid:
                                                        utm_ctx["ga4_property_id"] = best_pid
                                            except Exception:
                                                pass
                                        saved = history_save_func(
                                            final_url,
                                            utm_ctx.get("ga4_property_id") or ""
                                        )
                                        if saved:
                                            if hasattr(st, "toast"):
                                                st.toast("Link salvato nello storico UTM", icon="✅")
                                            else:
                                                st.success("Link salvato nello storico UTM.")
                                except Exception:
                                    pass

                except Exception as e:
                    st.session_state.messages.append({"role": "assistant", "content": f"Errore: {str(e)}"})
                finally:
                    st.session_state.chat_is_responding = False
                    st.session_state.pending_user_text = None

                st.rerun()




