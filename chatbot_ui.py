import logging
import streamlit as st
import streamlit.components.v1 as components
import re
import json
import hashlib
import html as html_lib
from html.parser import HTMLParser
from email import policy
from email.parser import BytesParser
from datetime import datetime
from io import BytesIO
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

import pandas as pd
import google.generativeai as genai
import ga4_mcp_tools  # Importa il modulo con i tool GA4
from utm_normalize import sanitize_utm_value as _sanitize_utm_value
from excel_parser import parse_excel_to_client_config

logger = logging.getLogger(__name__)


CHATBOT_GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-flash-latest",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
]


def _is_invalid_key_error(msg: str) -> bool:
    return "api key" in msg or "api_key" in msg or ("invalid" in msg and "key" in msg)


def _is_permission_error(msg: str) -> bool:
    return "permission" in msg or "403" in msg or "forbidden" in msg


def _is_model_not_found_error(msg: str) -> bool:
    return (
        "404" in msg
        or "not found" in msg
        or "not supported" in msg
        or "no longer available" in msg
    )


def _is_quota_error(msg: str) -> bool:
    return (
        "429" in msg
        or "quota" in msg
        or "resource exhausted" in msg
        or "rate limit" in msg
        or "too many requests" in msg
    )


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



# _sanitize_utm_value imported from utm_normalize


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


def _extract_client_campaign_types(client_rules_text: str) -> List[str]:
    values: List[str] = []
    for raw_line in str(client_rules_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = re.search(r"campaign_type usati:\s*(.+)$", line, flags=re.IGNORECASE)
        if not m:
            continue
        for token in m.group(1).split(","):
            clean = _sanitize_utm_value(token)
            if clean and clean not in values:
                values.append(clean)
    return values


def _normalize_utm_campaign_token_separators(utm_campaign: str, client_rules_text: str = "") -> str:
    """
    Enforce underscore separators between campaign tokens.
    Keep hyphens only inside a single token (e.g. promo-primavera).
    """
    value = (utm_campaign or "").strip().replace("`", "")
    if not value:
        return value

    value = _sanitize_utm_value(value)
    if not value:
        return ""

    # Already tokenized with underscore: keep as-is (except date normalization).
    if "_" in value:
        return _normalize_utm_campaign_date_token(value)

    # Nothing to normalize if there is no hyphen-based structure.
    if "-" not in value:
        return _normalize_utm_campaign_date_token(value)

    parts = [p for p in value.split("-") if p]
    if len(parts) < 3:
        # 1-2 segments likely a single token (e.g. promo-primavera)
        return _normalize_utm_campaign_date_token(value)

    known_types = set(_extract_client_campaign_types(client_rules_text))
    known_types.update({"promo", "promotional", "transactional", "editorial", "awareness", "awr", "tr", "ed"})
    second_token = _sanitize_utm_value(parts[1])

    # Conservative rewrite for common malformed outputs:
    # brandcountry-promotional-promoprimavera -> brandcountry_promotional_promoprimavera
    if second_token in known_types or len(parts) >= 3:
        head = [_sanitize_utm_value(parts[0]), second_token]
        tail = "-".join(parts[2:])
        normalized = "_".join([p for p in head if p] + ([tail] if tail else []))
        return _normalize_utm_campaign_date_token(normalized)

    return _normalize_utm_campaign_date_token(value)


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
        logger.debug("_rebuild_url_with_encoded_query: failed to re-encode URL, returning as-is")
        return url


def _extract_json_block_if_any(text: str) -> Optional[Dict[str, Any]]:
    """
    Se il modello stampa un JSON tra { ... } con chiavi utm_*, prova a parsarlo.
    """
    if not text or "utm_" not in text:
        return None
    # trova il primo blocco {...} "ampio"
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


class _AnchorExtractor(HTMLParser):
    """Collect anchor text + href from HTML mail bodies."""

    def __init__(self) -> None:
        super().__init__()
        self.entries: List[Dict[str, str]] = []
        self._in_anchor = False
        self._anchor_href = ""
        self._anchor_text_parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() != "a":
            return
        self._in_anchor = True
        self._anchor_text_parts = []
        href = ""
        for key, value in attrs:
            if str(key).lower() == "href":
                href = str(value or "").strip()
                break
        self._anchor_href = href

    def handle_data(self, data: str) -> None:
        if self._in_anchor and data:
            self._anchor_text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._in_anchor:
            return
        text = " ".join(self._anchor_text_parts).strip()
        text = re.sub(r"\s+", " ", html_lib.unescape(text))
        href = (self._anchor_href or "").strip()
        if text or href:
            self.entries.append({"text": text, "href": href})
        self._in_anchor = False
        self._anchor_href = ""
        self._anchor_text_parts = []


def _decode_bytes_fallback(raw: bytes) -> str:
    for enc in ["utf-8", "utf-8-sig", "latin-1"]:
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="ignore")


def _extract_html_texts_from_eml(raw: bytes) -> List[str]:
    try:
        msg = BytesParser(policy=policy.default).parsebytes(raw)
    except Exception:
        return []

    html_parts: List[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = str(part.get_content_type() or "").lower()
            if ctype not in {"text/html", "text/plain"}:
                continue
            try:
                payload = part.get_content()
            except Exception:
                payload = _decode_bytes_fallback(part.get_payload(decode=True) or b"")
            if payload:
                html_parts.append(str(payload))
    else:
        try:
            payload = msg.get_content()
        except Exception:
            payload = _decode_bytes_fallback(msg.get_payload(decode=True) or b"")
        if payload:
            html_parts.append(str(payload))
    return html_parts


def _extract_cta_entries_from_html(html_text: str) -> List[Dict[str, str]]:
    parser = _AnchorExtractor()
    try:
        parser.feed(str(html_text or ""))
    except Exception:
        return []
    return parser.entries


def _parse_rules_rows_from_uploaded_file(file_name: str, raw_bytes: bytes) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    ext = str(file_name or "").lower().rsplit(".", 1)[-1] if "." in str(file_name or "") else ""
    if ext == "csv":
        df = pd.read_csv(BytesIO(raw_bytes), dtype=str).fillna("")
        for _, row in df.iterrows():
            row_dict = {str(k): str(v) for k, v in row.to_dict().items()}
            row_dict["__sheet_name"] = "csv"
            rows.append(row_dict)
        return rows

    sheets = pd.read_excel(BytesIO(raw_bytes), sheet_name=None, dtype=str)
    for sheet_name, df in (sheets or {}).items():
        if df is None:
            continue
        safe_sheet_name = str(sheet_name or "").strip()[:80] or "__sheet__"
        for _, row in df.fillna("").iterrows():
            row_dict = {str(k): str(v) for k, v in row.to_dict().items()}
            row_dict["__sheet_name"] = safe_sheet_name
            rows.append(row_dict)
    return rows


def _extract_email_variants_from_text(user_input: str) -> List[Dict[str, str]]:
    text = str(user_input or "").strip()
    if not text:
        return []

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    candidates: List[str] = []
    for ln in lines:
        lnorm = ln.lower()
        if re.match(r"^[-*•\d\)\.]+\s*", lnorm):
            candidates.append(re.sub(r"^[-*•\d\)\.]+\s*", "", ln).strip())
            continue
        if (
            lnorm.startswith("a quelli")
            or lnorm.startswith("ai ")
            or lnorm.startswith("a tutti")
            or "clienti" in lnorm
        ):
            candidates.append(ln)

    # fallback: chunk by punctuation for compact messages
    if not candidates and any(k in text.lower() for k in ["mail", "email", "casistiche", "casistica"]):
        for piece in re.split(r"[;\n]+", text):
            p = piece.strip()
            if "client" in p.lower() and len(p.split()) >= 3:
                candidates.append(p)

    variants: List[Dict[str, str]] = []
    seen = set()
    for cand in candidates:
        clean_label = re.sub(r"\s+", " ", cand).strip(" .,:;-")
        if len(clean_label) < 4:
            continue
        token = _sanitize_utm_value(clean_label.replace("&", " e "))
        if not token:
            continue
        # keep token concise for UTM naming
        token_parts = [p for p in token.split("-") if p][:6]
        token_short = "-".join(token_parts)
        key = token_short.lower()
        if key in seen:
            continue
        seen.add(key)
        variants.append({"label": clean_label, "token": token_short})
        if len(variants) >= 8:
            break
    return variants


def _build_uploaded_files_signature(uploaded_files: List[Any]) -> str:
    if not uploaded_files:
        return ""
    digest = hashlib.sha256()
    for f in uploaded_files:
        try:
            raw = f.getvalue() or b""
        except Exception:
            raw = b""
        digest.update(str(getattr(f, "name", "")).encode("utf-8", errors="ignore"))
        digest.update(str(len(raw)).encode("ascii", errors="ignore"))
        digest.update(hashlib.sha256(raw).digest())
    return digest.hexdigest()


def _extract_cta_data_from_uploaded_files(uploaded_files: List[Any]) -> Dict[str, Any]:
    """
    Parse uploaded mail-like files and extract CTA labels/tokens as chatbot hints.
    """
    signature = _build_uploaded_files_signature(uploaded_files)
    result: Dict[str, Any] = {
        "signature": signature,
        "cta_labels": [],
        "cta_tokens": [],
        "cta_links": [],
        "uploaded_rule_sources": [],
        "uploaded_rule_mediums": [],
        "uploaded_rule_campaign_types": [],
        "uploaded_rule_campaign_examples": [],
        "file_summaries": [],
    }
    if not uploaded_files:
        return result

    generic_labels = {
        "clicca qui", "click here", "qui", "here", "link",
        "vai", "vai al sito", "scopri", "read more",
    }

    seen_labels = set()
    seen_tokens = set()
    seen_links = set()
    seen_rule_sources = set()
    seen_rule_mediums = set()
    seen_rule_campaign_types = set()
    seen_rule_campaign_examples = set()

    for up in uploaded_files:
        file_name = str(getattr(up, "name", "file")).strip() or "file"
        ext = file_name.lower().rsplit(".", 1)[-1] if "." in file_name else ""
        try:
            raw = up.getvalue() or b""
        except Exception:
            raw = b""
        body_chunks: List[str] = []
        if ext in {"html", "htm", "txt"}:
            body_chunks.append(_decode_bytes_fallback(raw))
        elif ext == "eml":
            body_chunks.extend(_extract_html_texts_from_eml(raw))
        else:
            body_chunks.append(_decode_bytes_fallback(raw))

        cta_count = 0
        for chunk in body_chunks:
            for entry in _extract_cta_entries_from_html(chunk):
                raw_label = str(entry.get("text", "")).strip()
                raw_href = str(entry.get("href", "")).strip()
                if raw_href and raw_href.lower() not in {"#", "javascript:void(0)"} and raw_href not in seen_links:
                    seen_links.add(raw_href)
                    if len(result["cta_links"]) < 20:
                        result["cta_links"].append(raw_href)

                if not raw_label:
                    continue
                label_norm = re.sub(r"\s+", " ", html_lib.unescape(raw_label)).strip()
                if len(label_norm) < 2 or len(label_norm) > 90:
                    continue
                if label_norm.lower() in generic_labels:
                    continue
                key = label_norm.lower()
                if key not in seen_labels:
                    seen_labels.add(key)
                    if len(result["cta_labels"]) < 20:
                        result["cta_labels"].append(label_norm)
                token = _sanitize_utm_value(label_norm.replace("&", " e "))
                if token and token not in seen_tokens:
                    seen_tokens.add(token)
                    if len(result["cta_tokens"]) < 20:
                        result["cta_tokens"].append(token)
                cta_count += 1

        if ext in {"xlsx", "xls", "csv"}:
            try:
                rules_rows = _parse_rules_rows_from_uploaded_file(file_name, raw)
                parsed_cfg = parse_excel_to_client_config(rules_rows)
                for src in parsed_cfg.get("sources", []) or []:
                    token = _sanitize_utm_value(str(src))
                    if token and token not in seen_rule_sources:
                        seen_rule_sources.add(token)
                        if len(result["uploaded_rule_sources"]) < 30:
                            result["uploaded_rule_sources"].append(token)
                for med in parsed_cfg.get("mediums", []) or []:
                    token = _sanitize_utm_value(str(med))
                    if token and token not in seen_rule_mediums:
                        seen_rule_mediums.add(token)
                        if len(result["uploaded_rule_mediums"]) < 30:
                            result["uploaded_rule_mediums"].append(token)
                for ctype in parsed_cfg.get("campaign_types", []) or []:
                    token = _sanitize_utm_value(str(ctype))
                    if token and token not in seen_rule_campaign_types:
                        seen_rule_campaign_types.add(token)
                        if len(result["uploaded_rule_campaign_types"]) < 20:
                            result["uploaded_rule_campaign_types"].append(token)
                for cex in parsed_cfg.get("campaign_examples", []) or []:
                    token = _sanitize_utm_value(str(cex))
                    if token and token not in seen_rule_campaign_examples:
                        seen_rule_campaign_examples.add(token)
                        if len(result["uploaded_rule_campaign_examples"]) < 20:
                            result["uploaded_rule_campaign_examples"].append(token)
            except Exception:
                logger.exception("Failed to parse uploaded naming convention file: %s", file_name)

        result["file_summaries"].append({"name": file_name, "ctas_found": cta_count})

    return result


def clean_bot_response(text: str, client_rules_text: str = "") -> str:
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

    # Se il modello ha già generato più URL UTM (casistiche multiple), non collassare a un solo link.
    all_full_urls = re.findall(r"https?://[^\s<>\"]+", text)
    utm_urls = [u for u in all_full_urls if "utm_" in u.lower()]
    if len(utm_urls) >= 2:
        return text

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
                clean_v = _normalize_utm_campaign_token_separators(clean_v, client_rules_text=client_rules_text)
            utm_pairs.append((k, clean_v))

        if base_url:
            p = urlparse(base_url)
            original_qs = parse_qsl(p.query, keep_blank_values=True)
            merged = original_qs + utm_pairs
            encoded = urlencode(merged, doseq=True, safe="")
            final_url = urlunparse((p.scheme, p.netloc, p.path, p.params, encoded, p.fragment))
            final_url = _rebuild_url_with_encoded_query(final_url)
            return "Copia e incolla questo link completo:\n" + final_url

    # Se il testo include un URL, prova a "ripulire" e re-encodare solo quello
    url_in_text = _extract_first_url(text)
    if url_in_text:
        norm = _normalize_destination_url(url_in_text)
        p = urlparse(norm)
        pairs = parse_qsl(p.query, keep_blank_values=True)
        cleaned_pairs = []
        for key, value in pairs:
            clean_value = (value or "").replace("`", "").strip()
            if key == "utm_campaign":
                clean_value = _normalize_utm_campaign_token_separators(clean_value, client_rules_text=client_rules_text)
            cleaned_pairs.append((key, clean_value))
        encoded = urlencode(cleaned_pairs, doseq=True, safe="")
        fixed = urlunparse((p.scheme, p.netloc, p.path, p.params, encoded, p.fragment))
        fixed = _rebuild_url_with_encoded_query(fixed)

        # Se il bot ha scritto testo + url, mantieni solo l'istruzione + url
        # (per rispettare la richiesta "output solo link")
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
        cta_tokens = context.get("uploaded_cta_tokens") or []
        if cta_tokens:
            examples = ", ".join([str(x) for x in cta_tokens[:4] if str(x).strip()])
            if examples:
                return (
                    "Perfetto. Prima del link finale vuoi valorizzare anche utm_content? "
                    f"Dai file caricati ho rilevato CTA utili, ad esempio: {examples}. "
                    "Confermi uno di questi o ne preferisci un altro?"
                )
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


def _enforce_multi_variant_guidance(raw_text: str, context: dict) -> str:
    """
    If multiple email variants are detected, ensure the assistant explicitly handles all cases.
    """
    text = str(raw_text or "").strip()
    if not text:
        return text

    variants = context.get("email_variants") or []
    if len(variants) < 2:
        return text

    low = text.lower()
    already_mentions_multi = any(
        marker in low
        for marker in ["casistiche", "casistica", "ciascun", "ciascuna", "ognuna", "ogni segmento", "varianti"]
    )
    if already_mentions_multi:
        return text

    labels = ", ".join([str(v.get("label", "")).strip() for v in variants[:4] if str(v.get("label", "")).strip()])
    if not labels:
        return text

    if "?" in text:
        return f"{text} Considero tutte le casistiche richieste: {labels}."
    return (
        f"{text}\n"
        f"Gestisco la richiesta in modalita multi-casistica e preparo UTM separati per: {labels}."
    )


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
            context["email_variants"] = []
            return

        plain_input = str(user_input or "").strip()
        input_lower = plain_input.lower()
        params = context["params"]
        context.setdefault("email_variants", [])

        url = _extract_first_url(user_input)
        if url and not params["destination_url"]:
            params["destination_url"] = _normalize_destination_url(url)

        has_explicit_utm = any(tag in input_lower for tag in ["utm_", "utm source", "utm medium", "utm campaign"])
        if plain_input and len(plain_input.split()) >= 5 and not has_explicit_utm and not params.get("campaign_brief"):
            params["campaign_brief"] = plain_input

        detected_variants = _extract_email_variants_from_text(plain_input)
        if detected_variants:
            existing_tokens = {
                str(v.get("token", "")).strip().lower()
                for v in (context.get("email_variants") or [])
                if isinstance(v, dict)
            }
            merged = list(context.get("email_variants") or [])
            for variant in detected_variants:
                vtok = str(variant.get("token", "")).strip().lower()
                if not vtok or vtok in existing_tokens:
                    continue
                merged.append({"label": variant.get("label", ""), "token": variant.get("token", "")})
                existing_tokens.add(vtok)
                if len(merged) >= 8:
                    break
            context["email_variants"] = merged

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
        logger.exception("_update_context_from_response: failed to extract context from response/input")


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
    default_destination_url: str = "",
    ga4_binding_state: Optional[Dict[str, Any]] = None,
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
    default_destination_url = str(default_destination_url or "").strip()
    uploaded_cta_labels = [str(x).strip() for x in (context.get("uploaded_cta_labels") or []) if str(x).strip()]
    uploaded_cta_tokens = [str(x).strip() for x in (context.get("uploaded_cta_tokens") or []) if str(x).strip()]
    uploaded_cta_links = [str(x).strip() for x in (context.get("uploaded_cta_links") or []) if str(x).strip()]
    uploaded_rule_sources = [str(x).strip() for x in (context.get("uploaded_rule_sources") or []) if str(x).strip()]
    uploaded_rule_mediums = [str(x).strip() for x in (context.get("uploaded_rule_mediums") or []) if str(x).strip()]
    uploaded_rule_campaign_types = [str(x).strip() for x in (context.get("uploaded_rule_campaign_types") or []) if str(x).strip()]
    uploaded_rule_campaign_examples = [str(x).strip() for x in (context.get("uploaded_rule_campaign_examples") or []) if str(x).strip()]
    email_variants = context.get("email_variants") or []
    uploaded_cta_block = ""
    if uploaded_cta_labels or uploaded_cta_tokens:
        labels_csv = ", ".join(uploaded_cta_labels[:8]) if uploaded_cta_labels else "nessuna CTA testuale rilevata"
        tokens_csv = ", ".join(uploaded_cta_tokens[:8]) if uploaded_cta_tokens else "nessun token CTA rilevato"
        links_csv = ", ".join(uploaded_cta_links[:5]) if uploaded_cta_links else "nessun link CTA rilevato"
        uploaded_cta_block = f"""
CONTESTO CTA DA FILE CARICATI (EMAIL/HTML/TXT/EML)
- CTA rilevate nel materiale caricato dall'utente: {labels_csv}
- Token utm-friendly derivati dalle CTA: {tokens_csv}
- Link CTA rilevati: {links_csv}
- Quando chiedi utm_content o token CTA di utm_campaign, usa questi esempi come priorita.
- Se i file mostrano CTA coerenti con la campagna, proponi direttamente quei token e chiedi solo conferma.
"""
    uploaded_rules_block = ""
    if uploaded_rule_sources or uploaded_rule_mediums or uploaded_rule_campaign_types or uploaded_rule_campaign_examples:
        uploaded_rules_block = f"""
REGOLE DA FILE ALLEGATI IN CHAT (NOMING CONVENTION CLIENTE)
- utm_source rilevati dal file allegato: {", ".join(uploaded_rule_sources[:12]) if uploaded_rule_sources else "non rilevati"}
- utm_medium rilevati dal file allegato: {", ".join(uploaded_rule_mediums[:12]) if uploaded_rule_mediums else "non rilevati"}
- campaign_type rilevati dal file allegato: {", ".join(uploaded_rule_campaign_types[:10]) if uploaded_rule_campaign_types else "non rilevati"}
- esempi utm_campaign dal file allegato: {", ".join(uploaded_rule_campaign_examples[:8]) if uploaded_rule_campaign_examples else "non rilevati"}
- Se presenti, usa queste convenzioni come vincolo primario insieme alle regole cliente gia configurate.
"""
    variants_block = ""
    if email_variants:
        variants_csv = ", ".join(
            [str(v.get("label", "")).strip() for v in email_variants[:8] if str(v.get("label", "")).strip()]
        )
        variants_tokens_csv = ", ".join(
            [str(v.get("token", "")).strip() for v in email_variants[:8] if str(v.get("token", "")).strip()]
        )
        variants_block = f"""
CASELISTE/AUDIENCE RILEVATE NELLA RICHIESTA
- Casistiche richieste: {variants_csv}
- Token audience suggeriti per distinguere i link: {variants_tokens_csv}
- Per richieste multi-casistica devi preparare un set UTM separato per ogni casistica.
"""
    client_rules_block = ""
    if client_rules_text:
        client_rules_block = f"""
REGOLE CLIENTE (PRIORITARIE)
- Applica queste regole specifiche del cliente prima dei mapping generici.
- Se ci sono conflitti tra regole generiche e regole cliente, vincono le regole cliente.
{client_rules_text}
"""
    property_preselection_block = ""
    binding = ga4_binding_state if isinstance(ga4_binding_state, dict) else {}
    lock_mode = bool(binding.get("lock_mode"))
    lock_accessible = bool(binding.get("is_accessible"))
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

    ga4_lock_enforcement_block = ""
    if lock_mode and preferred_pid:
        access_msg = "disponibile" if lock_accessible else "non disponibile"
        property_preselection_block = f"""
PROPERTY CLIENTE VINCOLATA (LOCK ATTIVO)
- Property cliente vincolata da configurazione: {preferred_label or f"properties/{preferred_pid}"} (properties/{preferred_pid}).
- NON chiedere all'utente di scegliere/cambiare property.
- NON accettare property alternative anche se richieste.
- Se GA4 non e accessibile (permessi mancanti/errore), continua con le regole cliente da file UTM senza fermare il flusso.
"""
        ga4_lock_enforcement_block = f"""
PROPERTY GA4: LOCK CLIENTE ATTIVO
- Property vincolata a properties/{preferred_pid} (accesso {access_msg}).
- NON usare tool_guess_property_from_url per cambiare property.
- NON proporre property alternative.
- Se accesso GA4 non disponibile, continua il flusso con sole regole UTM cliente.
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
 {uploaded_cta_block}
 {uploaded_rules_block}
 {variants_block}

REGOLE VISIVE
1) Solo testo semplice (no HTML, no markdown complesso, no blocchi di codice).
2) UNA sola domanda per messaggio.
3) OUTPUT FINALE: stampa SOLO il link completo con un'istruzione del tipo "Copia e incolla questo link completo:".
   NON stampare JSON, NON usare parentesi graffe.
   ECCEZIONE: se la richiesta contiene più casistiche/audience, stampa "Copia e incolla questi link completi:"
   e poi un link completo separato per ciascuna casistica, etichettato con la relativa audience.
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
- Non usare trattini per separare i token principali di utm_campaign: tra token usa sempre underscore.
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
{ga4_lock_enforcement_block}

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
- Se sono disponibili CTA estratte dai file caricati, usale come riferimento primario per la parte CTA.
- Se sono presenti più casistiche audience, genera un utm_campaign distinto per ciascuna (o token variante in utm_content, secondo regole cliente).
STEP 7: utm_content
- Anche se opzionale, chiedilo sempre prima del link finale.
- Fai una domanda concreta sul contenuto creativo, per esempio CTA, bottone, banner, hero, visual o placement.
- Se sono disponibili CTA estratte dai file caricati, proponi almeno 2 esempi reali tra quelli estratti.
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
- CTA da file caricati (testo): {", ".join(uploaded_cta_labels[:6]) if uploaded_cta_labels else "non disponibili"}
- CTA da file caricati (token): {", ".join(uploaded_cta_tokens[:6]) if uploaded_cta_tokens else "non disponibili"}
- Casistiche audience rilevate: {", ".join([str(v.get("label", "")).strip() for v in email_variants[:6] if str(v.get("label", "")).strip()]) if email_variants else "non rilevate"}

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
class GeminiError(Exception):
    """User-facing Gemini error with actionable message."""
    pass


def _classify_gemini_error(error: Exception) -> str:
    """Return a user-friendly Italian message based on the error type."""
    msg = str(error).lower()

    if _is_invalid_key_error(msg):
        return (
            "Chiave Gemini di sistema non valida o scaduta. "
            "Contatta l'amministratore del tool."
        )
    if _is_permission_error(msg):
        return (
            "Accesso ai modelli Gemini non autorizzato per la chiave di sistema. "
            "Contatta l'amministratore del tool."
        )
    if _is_model_not_found_error(msg):
        return (
            "La configurazione del modello Gemini del tool non e aggiornata. "
            "Contatta l'amministratore del tool."
        )
    if _is_quota_error(msg):
        return (
            "Limite di utilizzo raggiunto per il servizio AI condiviso. "
            "Riprova tra qualche minuto o contatta l'amministratore del tool se il problema persiste."
        )
    if "500" in msg or "internal" in msg or "unavailable" in msg or "503" in msg:
        return (
            "Il servizio Gemini è temporaneamente non disponibile. "
            "Riprova tra qualche minuto."
        )
    if "timeout" in msg or "deadline" in msg:
        return (
            "La richiesta ha impiegato troppo tempo. "
            "Riprova con un messaggio più breve."
        )
    return f"Errore imprevisto dal servizio AI: {str(error)[:200]}"


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
    Raises GeminiError con messaggio user-friendly.
    """
    models_to_try = CHATBOT_GEMINI_MODELS

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

            # Model not available — try next
            if _is_model_not_found_error(error_str):
                continue
            # Auth/permission error — no point trying other models
            if _is_invalid_key_error(error_str) or _is_permission_error(error_str):
                raise GeminiError(_classify_gemini_error(e)) from e
            # Quota/rate limit — no point trying other models
            if _is_quota_error(error_str):
                raise GeminiError(_classify_gemini_error(e)) from e
            # Other error — try next model
            continue

    raise GeminiError(_classify_gemini_error(
        last_error or Exception("Nessun modello Gemini disponibile")
    ))


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
    default_destination_url: str = "",
    ga4_binding_state: Optional[Dict[str, Any]] = None,
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
    if "chat_uploaded_cta_data" not in st.session_state:
        st.session_state.chat_uploaded_cta_data = {
            "signature": "",
            "cta_labels": [],
            "cta_tokens": [],
            "cta_links": [],
            "uploaded_rule_sources": [],
            "uploaded_rule_mediums": [],
            "uploaded_rule_campaign_types": [],
            "uploaded_rule_campaign_examples": [],
            "file_summaries": [],
        }
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
            "uploaded_cta_labels": [],
            "uploaded_cta_tokens": [],
            "uploaded_cta_links": [],
            "uploaded_rule_sources": [],
            "uploaded_rule_mediums": [],
            "uploaded_rule_campaign_types": [],
            "uploaded_rule_campaign_examples": [],
            "email_variants": [],
        }
    # Backward compatibility: allinea eventuali sessioni vecchie ai nuovi campi.
    st.session_state.utm_context.setdefault("current_step", 0)
    st.session_state.utm_context.setdefault("optional_step", "content")
    st.session_state.utm_context.setdefault("ga4_property_id", None)
    st.session_state.utm_context.setdefault("tool_cache", {})
    st.session_state.utm_context.setdefault("uploaded_cta_labels", [])
    st.session_state.utm_context.setdefault("uploaded_cta_tokens", [])
    st.session_state.utm_context.setdefault("uploaded_cta_links", [])
    st.session_state.utm_context.setdefault("uploaded_rule_sources", [])
    st.session_state.utm_context.setdefault("uploaded_rule_mediums", [])
    st.session_state.utm_context.setdefault("uploaded_rule_campaign_types", [])
    st.session_state.utm_context.setdefault("uploaded_rule_campaign_examples", [])
    st.session_state.utm_context.setdefault("email_variants", [])
    st.session_state.utm_context.setdefault("params", {})
    for _k in [
        "destination_url", "campaign_brief", "traffic_type", "ga4_channel",
        "utm_medium", "utm_source", "utm_campaign", "utm_content", "utm_term",
        "campaign_country_language", "campaign_type", "campaign_name", "campaign_date", "campaign_cta",
    ]:
        st.session_state.utm_context["params"].setdefault(_k, None)
    binding = ga4_binding_state if isinstance(ga4_binding_state, dict) else {}
    lock_mode = bool(binding.get("lock_mode"))
    lock_accessible = bool(binding.get("is_accessible"))
    current_profile_signature = hashlib.sha256(
        (
            f"{client_rules_text}|{preferred_property_id}|{preferred_property_name}|{default_destination_url}"
            f"|lock:{lock_mode}|ga4_access:{lock_accessible}|reason:{binding.get('reason', '')}"
        ).encode("utf-8")
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
            "uploaded_cta_labels": [],
            "uploaded_cta_tokens": [],
            "uploaded_cta_links": [],
            "uploaded_rule_sources": [],
            "uploaded_rule_mediums": [],
            "uploaded_rule_campaign_types": [],
            "uploaded_rule_campaign_examples": [],
            "email_variants": [],
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
    
    # --- CSS (loaded from file) ---
    from pathlib import Path as _Path
    _chatbot_css_path = _Path(__file__).with_name("styles") / "chatbot.css"
    st.markdown(f"<style>{_chatbot_css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

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
            header_col, close_col = st.columns([0.9, 0.1], gap="small")
            with header_col:
                st.markdown(
                    '<div class="chat-header"><span class="chat-header-logo">W</span><span class="chat-header-text"><span class="chat-header-title">Smart UTM Assistant</span><span class="chat-header-sub">Percorso guidato per creare URL UTM coerenti e puliti</span></span></div>',
                    unsafe_allow_html=True,
                )
            with close_col:
                if st.button("✕", key="chat_close_btn", help="Chiudi chatbot", use_container_width=True):
                    st.session_state.chat_visible = False
                    st.rerun()

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
            uploaded_reference_files = st.file_uploader(
                "Carica file email di riferimento (opzionale)",
                type=["html", "htm", "eml", "txt", "xlsx", "xls", "csv"],
                accept_multiple_files=True,
                key="chat_reference_files",
                disabled=chat_locked,
                help="Il chatbot puo leggere CTA/link da email (HTML/TXT/EML) e naming convention da file Excel/CSV per suggerire UTM coerenti.",
            )

            current_upload_sig = _build_uploaded_files_signature(uploaded_reference_files or [])
            cached_upload_data = st.session_state.get("chat_uploaded_cta_data", {})
            if current_upload_sig and cached_upload_data.get("signature") == current_upload_sig:
                upload_cta_data = cached_upload_data
            else:
                upload_cta_data = _extract_cta_data_from_uploaded_files(uploaded_reference_files or [])
                st.session_state.chat_uploaded_cta_data = upload_cta_data

            st.session_state.utm_context["uploaded_cta_labels"] = list(upload_cta_data.get("cta_labels", []))
            st.session_state.utm_context["uploaded_cta_tokens"] = list(upload_cta_data.get("cta_tokens", []))
            st.session_state.utm_context["uploaded_cta_links"] = list(upload_cta_data.get("cta_links", []))
            st.session_state.utm_context["uploaded_rule_sources"] = list(upload_cta_data.get("uploaded_rule_sources", []))
            st.session_state.utm_context["uploaded_rule_mediums"] = list(upload_cta_data.get("uploaded_rule_mediums", []))
            st.session_state.utm_context["uploaded_rule_campaign_types"] = list(upload_cta_data.get("uploaded_rule_campaign_types", []))
            st.session_state.utm_context["uploaded_rule_campaign_examples"] = list(upload_cta_data.get("uploaded_rule_campaign_examples", []))

            cta_tokens_preview = [str(x) for x in upload_cta_data.get("cta_tokens", []) if str(x).strip()]
            if cta_tokens_preview:
                st.caption(f"CTA rilevate dai file caricati: {', '.join(cta_tokens_preview[:6])}")
            uploaded_mediums_preview = [str(x) for x in upload_cta_data.get("uploaded_rule_mediums", []) if str(x).strip()]
            if uploaded_mediums_preview:
                st.caption(f"Naming (utm_medium) rilevato dai file: {', '.join(uploaded_mediums_preview[:6])}")
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

            if submitted and not chat_locked:
                if user_text:
                    _queue_user_message(user_text)
                elif cta_tokens_preview:
                    _queue_user_message(
                        "Ho caricato file email di riferimento: usa le CTA estratte per guidarmi su utm_content e token CTA."
                    )
            if st.session_state.chat_is_responding and st.session_state.pending_user_text:
                pending_text = st.session_state.pending_user_text

                try:
                    with st.spinner("Smart UTM Assistant sta rispondendo..."):
                        api_key = st.session_state.get("gemini_api_key")
                        if not api_key:
                            st.session_state.messages.append(
                                {"role": "assistant", "content": "La chiave Gemini non e configurata lato sistema. Contatta l'amministratore del tool."}
                            )
                        else:
                            genai.configure(api_key=api_key)
                            utm_ctx = st.session_state.utm_context
                            if lock_mode and preferred_pid_ctx:
                                utm_ctx["ga4_property_id"] = preferred_pid_ctx

                            def _bound_property_id(property_id: str) -> str:
                                pid = str(property_id or "").replace("properties/", "").strip()
                                if lock_mode and preferred_pid_ctx:
                                    return preferred_pid_ctx
                                return pid

                            def _ga4_blocked_response() -> Dict[str, Any]:
                                return {
                                    "error": (
                                        "Accesso GA4 non disponibile per la property configurata "
                                        f"(properties/{preferred_pid_ctx}). Proseguo con regole UTM cliente."
                                    ),
                                    "error_type": "PropertyAccessUnavailable",
                                }
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
                                if lock_mode and preferred_pid_ctx and not lock_accessible:
                                    return _ga4_blocked_response()
                                return ga4_mcp_tools.get_property_details(_bound_property_id(property_id), creds)

                            def tool_run_report(property_id: str, dimensions: List[str], metrics: List[str], start_date: str = "30daysAgo", end_date: str = "today") -> Any:
                                bound_pid = _bound_property_id(property_id)
                                if lock_mode and preferred_pid_ctx and not lock_accessible:
                                    return _ga4_blocked_response()
                                cache_key = f"run_report:{bound_pid}:{dimensions}:{metrics}:{start_date}:{end_date}"
                                if cache_key in utm_ctx["tool_cache"]:
                                    return utm_ctx["tool_cache"][cache_key]
                                result = ga4_mcp_tools.run_report(bound_pid, dimensions, metrics, [{"start_date": start_date, "end_date": end_date}], creds)
                                utm_ctx["tool_cache"][cache_key] = result
                                return result

                            def tool_run_realtime_report(property_id: str, dimensions: List[str], metrics: List[str]) -> Any:
                                if lock_mode and preferred_pid_ctx and not lock_accessible:
                                    return _ga4_blocked_response()
                                return ga4_mcp_tools.run_realtime_report(_bound_property_id(property_id), dimensions, metrics, creds)

                            def tool_list_ads_links(property_id: str) -> Any:
                                if lock_mode and preferred_pid_ctx and not lock_accessible:
                                    return _ga4_blocked_response()
                                return ga4_mcp_tools.list_google_ads_links(_bound_property_id(property_id), creds)

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
                            if not lock_mode:
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
                                default_destination_url=default_destination_url,
                                ga4_binding_state=binding,
                            )

                            # --- History ---
                            history = []
                            for msg in st.session_state.messages:
                                if msg == st.session_state.messages[-1]:
                                    continue
                                role = "user" if msg["role"] == "user" else "model"
                                text = msg.get("raw_content", msg["content"])
                                history.append({"role": role, "parts": [text]})

                            # Rate limit check
                            from rate_limit import check_rate_limit
                            _rl_key = st.session_state.get("user_email", "anon")
                            _rl_ok, _rl_wait = check_rate_limit(_rl_key)
                            if not _rl_ok:
                                cleaned = f"Troppi messaggi. Riprova tra {_rl_wait:.0f} secondi."
                            else:
                                response_text, _ = get_gemini_response_safe(
                                    pending_text,
                                    history,
                                    my_tools,
                                    system_instruction,
                                    api_key,
                                )
                                cleaned = clean_bot_response(response_text, client_rules_text=client_rules_text)
                                cleaned = _enforce_guided_single_question(cleaned, utm_ctx)
                                cleaned = _enforce_client_rule_options(cleaned, utm_ctx, client_rules_text)
                                cleaned = _enforce_optional_followup(cleaned, utm_ctx)
                                cleaned = _enforce_multi_variant_guidance(cleaned, utm_ctx)

                            st.session_state.messages.append(
                                {
                                    "role": "assistant",
                                    "content": cleaned,
                                    "raw_content": response_text if _rl_ok else cleaned,
                                }
                            )

                            # Update conversation context (skip if rate-limited)
                            if _rl_ok:
                                _update_context_from_response(response_text, pending_text, utm_ctx)

                            # Salva automaticamente nello storico UTM, se disponibile un link finale.
                            if _rl_ok and callable(history_save_func):
                                try:
                                    final_url = _extract_first_url(cleaned or "")
                                    if final_url and "utm_" in final_url:
                                        # Retry auto-selezione property se ancora mancante
                                        # usando prima URL di destinazione, poi URL finale.
                                        if not lock_mode and not utm_ctx.get("ga4_property_id"):
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
                                            (preferred_pid_ctx if (lock_mode and preferred_pid_ctx) else (utm_ctx.get("ga4_property_id") or ""))
                                        )
                                        if saved:
                                            if hasattr(st, "toast"):
                                                st.toast("Link salvato nello storico UTM")
                                            else:
                                                st.success("Link salvato nello storico UTM.")
                                except Exception:
                                    pass

                except GeminiError as e:
                    st.session_state.messages.append({"role": "assistant", "content": str(e)})
                except Exception as e:
                    logger.exception("Unexpected error in chatbot")
                    st.session_state.messages.append({"role": "assistant", "content": f"Errore imprevisto: {str(e)[:200]}"})
                finally:
                    st.session_state.chat_is_responding = False
                    st.session_state.pending_user_text = None

                st.rerun()

