"""
Client config rule extraction and campaign validation logic.

Pure functions extracted from app.py.
No Streamlit dependencies.
"""
import re
from datetime import datetime, timedelta
from utm_normalize import normalize_token, normalize_medium_token


def _split_rule_values(value: str) -> list:
    """Split a rule cell value by comma, pipe, semicolon, or slash."""
    raw = str(value or "").strip()
    if not raw:
        return []
    return [x.strip() for x in re.split(r"[,\|;/]+", raw) if str(x).strip()]


def order_by_ga4_priority(options, ga4_priority, normalizer):
    """Order options by GA4 popularity (sessions) first, then alphabetical fallback."""
    values = []
    seen = set()
    for raw in options or []:
        v = normalizer(raw)
        if v and v not in seen:
            values.append(v)
            seen.add(v)

    priority = []
    seen_p = set()
    for raw in ga4_priority or []:
        v = normalizer(raw)
        if v and v not in seen_p:
            priority.append(v)
            seen_p.add(v)

    head = [v for v in priority if v in seen]
    tail = sorted([v for v in values if v not in set(head)])
    return head + tail

def extract_client_rule_values(client_config: dict):
    rows = (client_config or {}).get("rules_rows", []) or []
    source_keys = {"utm_source", "source"}
    medium_keys = {"utm_medium", "medium"}
    campaign_type_keys = {"campaigntype", "campaign_type", "type"}
    sources = set()
    mediums = set()
    campaign_types = set()

    def normalize_key(value: str) -> str:
        key = str(value or "").strip().lower()
        key = key.replace(" ", "_")
        key = re.sub(r"[^a-z0-9_]", "", key)
        return key

    # 1) parsing diretto per colonne gi? nominate
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key, raw_val in row.items():
            norm_key = normalize_key(key)
            tokens = _split_rule_values(raw_val)
            if not tokens:
                continue
            if norm_key in source_keys:
                for t in tokens:
                    v = normalize_token(t)
                    if v:
                        sources.add(v)
            if norm_key in medium_keys:
                for t in tokens:
                    v = normalize_medium_token(t)
                    if v:
                        mediums.add(v)
            if norm_key in campaign_type_keys:
                for t in tokens:
                    v = normalize_token(t)
                    if v:
                        campaign_types.add(v)

    # 2) parsing tabellare per file excel importati con Unnamed:* e header in riga
    role_map_by_sheet = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        sheet_name = str(row.get("__sheet_name", "")).strip().lower() or "__default__"
        current_map = dict(role_map_by_sheet.get(sheet_name, {}))
        header_detected = False
        for key, raw_val in row.items():
            val_norm = normalize_key(str(raw_val or ""))
            if val_norm in source_keys:
                current_map[str(key)] = "source"
                header_detected = True
            elif val_norm in medium_keys:
                current_map[str(key)] = "medium"
                header_detected = True
            elif val_norm in campaign_type_keys:
                current_map[str(key)] = "campaign_type"
                header_detected = True
        if header_detected:
            role_map_by_sheet[sheet_name] = current_map
            continue
        if not current_map:
            continue
        for col_key, role in current_map.items():
            for t in _split_rule_values(row.get(col_key, "")):
                norm_t = normalize_token(t)
                if not norm_t:
                    continue
                if norm_t in source_keys or norm_t in medium_keys or norm_t in campaign_type_keys:
                    continue
                if role == "source":
                    sources.add(norm_t)
                elif role == "medium":
                    mediums.add(normalize_medium_token(t))
                elif role == "campaign_type":
                    campaign_types.add(norm_t)    # 3) estrazione robusta campaign_type
    # Reset: i passaggi precedenti possono includere rumore da header tabellari.
    campaign_types = set()

    blacklist = {
        "campaign", "campaignname", "campaigngoal", "campaign_goal", "campaign_name",
        "header", "footer", "data", "term", "content", "eccezione",
        "elemento", "token", "valori", "ammessi", "esempi", "regole", "note",
        "email", "adv"
    }

    # 3a) Riga esplicita "Campaign Type" nel foglio regole: valori in Unnamed:2
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_type_label = normalize_key(row.get("Unnamed: 1", ""))
        if row_type_label not in {"campaign_type", "campaigntype"}:
            continue

        for token in _split_rule_values(row.get("Unnamed: 2", "")):
            # Gestisce formati tipo: "pr (promotional)", "tr (transactional)", "editorial"
            words = re.findall(r"[A-Za-z][A-Za-z0-9_-]+", str(token))
            for w in words:
                v = normalize_token(w)
                if not v or v in blacklist or v.isdigit():
                    continue
                campaign_types.add(v)

    # 3b) Pattern da esempi URL/query: utm_campaign=brandcountry_type_name_date
    for row in rows:
        if not isinstance(row, dict):
            continue
        for raw_val in row.values():
            text = str(raw_val or "")
            if not text:
                continue

            for m in re.findall(r"utm_campaign=([A-Za-z0-9_\-]+)", text, flags=re.IGNORECASE):
                token = normalize_token(m)
                parts = [p for p in re.split(r"[_-]+", token) if p]
                if len(parts) >= 3:
                    ctype = normalize_token(parts[1])
                    if ctype and ctype not in blacklist and not ctype.isdigit():
                        campaign_types.add(ctype)

    # Pulizia finale
    campaign_types = {ct for ct in campaign_types if ct and ct not in blacklist and not ct.isdigit()}
    return sorted(sources), sorted(mediums), sorted(campaign_types)

def extract_client_field_examples(client_config: dict):
    rows = (client_config or {}).get("rules_rows", []) or []
    samples = {
        "campaign_name": [],
        "campaign_type": [],
        "utm_content": [],
        "utm_term": [],
        "country_language": [],
    }
    seen = {k: set() for k in samples}

    def normalize_key(value: str) -> str:
        key = str(value or "").strip().lower()
        key = key.replace(" ", "_")
        key = re.sub(r"[^a-z0-9_]", "", key)
        return key

    def push(field: str, raw: str, *, keep_medium: bool = False):
        if field not in samples:
            return
        token = normalize_medium_token(raw) if keep_medium else normalize_token(raw)
        if not token:
            return
        if token in {"utm_campaign", "utm_content", "utm_term", "campaign_name", "campaign_type"}:
            return
        if token in seen[field]:
            return
        seen[field].add(token)
        samples[field].append(token)

    # 1) Estraggo esempi diretti dalle righe regole (colonna Unnamed: 1 -> valori in Unnamed: 2)
    for row in rows:
        if not isinstance(row, dict):
            continue
        label_norm = normalize_key(row.get("Unnamed: 1", ""))
        value_raw = str(row.get("Unnamed: 2", "") or "")
        if not value_raw:
            continue

        if label_norm in {"campaign_name", "campaignname"}:
            for token in _split_rule_values(value_raw):
                push("campaign_name", token)
        elif label_norm in {"campaign_type", "campaigntype"}:
            for token in _split_rule_values(value_raw):
                words = re.findall(r"[A-Za-z][A-Za-z0-9_-]+", str(token))
                for w in words:
                    push("campaign_type", w)
        elif "utm_content" in label_norm or label_norm in {"content"}:
            for token in _split_rule_values(value_raw):
                push("utm_content", token)
        elif "utm_term" in label_norm or label_norm in {"term"}:
            for token in _split_rule_values(value_raw):
                push("utm_term", token)
        elif label_norm in {"country", "country_lingua", "country_language", "lingua", "language", "mercato", "market", "paese"}:
            for token in _split_rule_values(value_raw):
                push("country_language", token)

    # 2) Estraggo esempi dalle URL di esempio presenti nel file
    for row in rows:
        if not isinstance(row, dict):
            continue
        for raw_val in row.values():
            text = html_lib.unescape(str(raw_val or ""))
            if not text:
                continue

            for m in re.findall(r"utm_campaign=([A-Za-z0-9_\-]+)", text, flags=re.IGNORECASE):
                token = normalize_token(m)
                parts = [p for p in re.split(r"[_-]+", token) if p]
                if parts:
                    lead = normalize_token(parts[0])
                    if re.fullmatch(r"[a-z]{2,3}", lead or ""):
                        push("country_language", lead)
                if len(parts) >= 4:
                    push("campaign_type", parts[1])
                    push("campaign_name", "_".join(parts[2:-1]))
                elif len(parts) >= 3:
                    push("campaign_type", parts[1])
                    push("campaign_name", parts[2])

            for m in re.findall(r"utm_content=([A-Za-z0-9_\-]+)", text, flags=re.IGNORECASE):
                push("utm_content", m)
            for m in re.findall(r"utm_term=([A-Za-z0-9_\-]+)", text, flags=re.IGNORECASE):
                push("utm_term", m)

    return samples

def build_placeholder_examples(values, fallback: str, limit: int = 3) -> str:
    cleaned = [str(v).strip() for v in (values or []) if str(v).strip()]
    return ", ".join(cleaned[:limit]) if cleaned else fallback

def extract_client_campaign_rule_notes(client_config: dict):
    rows = (client_config or {}).get("rules_rows", []) or []
    notes = []
    examples = []
    seen_notes = set()
    seen_examples = set()

    for row in rows:
        if not isinstance(row, dict):
            continue
        for raw_val in row.values():
            text = html_lib.unescape(str(raw_val or ""))
            if not text:
                continue
            cleaned = text.replace("<br>", " ").replace("<br/>", " ").replace("<br />", " ")
            cleaned = re.sub(r"<[^>]+>", " ", cleaned)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            if not cleaned:
                continue

            lowered = cleaned.lower()
            if (
                "struttura email marketing" in lowered
                or "struttura campagne adv" in lowered
                or ("utm_campaign" in lowered and ("struttura" in lowered or "esempio" in lowered))
            ):
                if cleaned not in seen_notes:
                    seen_notes.add(cleaned)
                    notes.append(cleaned)

            for pattern in (r"utm_campaign\s*=\s*([a-z0-9_-]+)", r"utm_campaign=([a-z0-9_-]+)"):
                for match in re.findall(pattern, lowered, flags=re.IGNORECASE):
                    example = normalize_token(match)
                    if example and example not in seen_examples:
                        seen_examples.add(example)
                        examples.append(example)

    return notes[:4], examples[:5]

def extract_client_medium_source_map(client_config: dict):
    rows = (client_config or {}).get("rules_rows", []) or []
    mapping = {}

    for row in rows:
        if not isinstance(row, dict):
            continue
        sheet_name = str(row.get("__sheet_name", "") or "").strip().lower()
        if "sorgente" not in sheet_name and "mezzo" not in sheet_name and "naming convention" not in sheet_name:
            continue

        medium = normalize_medium_token(row.get("Unnamed: 1", ""))
        if not medium or medium in {"utm_medium", "medium", "none"}:
            continue

        raw_sources = _split_rule_values(row.get("Unnamed: 2", ""))
        cleaned_sources = []
        for token in raw_sources:
            source = normalize_token(token)
            if not source or source in {"utm_source", "source", "none"}:
                continue
            cleaned_sources.append(source)

        if not cleaned_sources:
            continue

        bucket = mapping.setdefault(medium, set())
        bucket.update(cleaned_sources)

    return {medium: sorted(values) for medium, values in mapping.items() if values}

def get_last_full_week_range(reference_date=None):
    ref = reference_date or datetime.today().date()
    current_week_monday = ref - timedelta(days=ref.weekday())
    end_date = current_week_monday - timedelta(days=1)
    start_date = end_date - timedelta(days=6)
    return start_date, end_date

def is_monday(reference_date=None):
    ref = reference_date or datetime.today().date()
    return ref.weekday() == 0

def validate_campaign_value_against_client_rules(raw_campaign: str, client_config: dict):
    issues = []
    raw = str(raw_campaign or '').strip()
    if not raw:
        return ['utm_campaign mancante']

    if raw != raw.lower():
        issues.append('utm_campaign deve usare solo minuscole')
    if re.search(r'\s', raw):
        issues.append('utm_campaign non deve contenere spazi')
    if re.search(r'[^A-Za-z0-9_-]', raw):
        issues.append('utm_campaign contiene caratteri speciali')

    campaign = str(raw).strip().lower()
    parts = [p for p in re.split(r'_+', campaign) if p]
    if len(parts) < 4:
        issues.append('utm_campaign dovrebbe avere almeno 4 token')

    _sources, _mediums, campaign_types = extract_client_rule_values(client_config)
    allowed_campaign_types = {normalize_token(x) for x in (campaign_types or []) if normalize_token(x)}
    if allowed_campaign_types and len(parts) >= 2:
        ctype = normalize_token(parts[1])
        if ctype and ctype not in allowed_campaign_types:
            issues.append('campaign_type non coerente con la convenzione cliente')

    campaign_notes, campaign_examples = extract_client_campaign_rule_notes(client_config)
    if any('brandcountry' in note.lower() for note in campaign_notes) and parts:
        if re.fullmatch(r'[a-z]{2,3}(?:-[a-z]{2})?', parts[0]):
            issues.append('primo token utm_campaign non coerente: atteso brandcountry')

    example_token_counts = [len([p for p in example.split('_') if p]) for example in (campaign_examples or []) if example]
    if example_token_counts and len(parts) < min(example_token_counts):
        issues.append('numero di token utm_campaign inferiore agli esempi cliente')

    example_has_date = any(
        any(re.fullmatch(r'\d{8}', token) for token in str(example).split('_'))
        for example in (campaign_examples or [])
    )
    if example_has_date and not any(re.fullmatch(r'\d{8}', token) for token in parts):
        issues.append('manca il token data in formato GGMMAAAA')

    return issues

def audit_ga4_campaign_entry(session_source: str, session_medium: str, session_campaign: str, observed_channel: str, client_config: dict):
    allowed_sources, allowed_mediums, _campaign_types = extract_client_rule_values(client_config)
    medium_source_map = extract_client_medium_source_map(client_config)

    source = normalize_token(session_source)
    medium = normalize_medium_token(session_medium)
    issues = []

    if allowed_mediums and medium not in set(allowed_mediums):
        issues.append('utm_medium fuori convenzione cliente')
    if allowed_sources and source not in set(allowed_sources):
        issues.append('utm_source fuori convenzione cliente')

    allowed_for_medium = set(medium_source_map.get(medium, []) or [])
    if allowed_for_medium and source not in allowed_for_medium:
        issues.append('coppia utm_source / utm_medium non prevista dal file cliente')

    issues.extend(validate_campaign_value_against_client_rules(session_campaign, client_config))

    expected_channel = infer_expected_channel_group(medium)
    observed = str(observed_channel or 'Unassigned').strip() or 'Unassigned'
    if expected_channel != 'Other' and observed and observed != expected_channel:
        issues.append(f'canale GA4 osservato {observed} invece di {expected_channel}')

    if not issues:
        status = 'OK'
        message = 'Campagna coerente con configurazione cliente e canalizzazione attesa'
    else:
        is_error = any(
            key in issue for issue in issues for key in [
                'fuori convenzione',
                'non prevista',
                'primo token',
            ]
        )
        status = 'ERROR' if is_error else 'WARNING'
        message = '; '.join(issues[:4])

    return {
        'status': status,
        'message': message,
        'expected_channel': expected_channel,
        'observed_channel': observed,
        'issues': issues,
    }
