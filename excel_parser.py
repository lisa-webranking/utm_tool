"""
Excel UTM Builder file parser.

Extracts structured UTM rule data from raw Excel/CSV rows at upload time.
This logic runs ONCE when the user uploads a file, not at every page load.
The extracted data is saved as typed arrays in the client config.
"""
import re
from utm_normalize import normalize_token, normalize_medium_token


def _split_rule_values(value: str) -> list:
    """Split a rule cell value by comma, pipe, semicolon, or slash."""
    raw = str(value or "").strip()
    if not raw:
        return []
    return [x.strip() for x in re.split(r"[,\|;/]+", raw) if str(x).strip()]


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


def parse_excel_to_client_config(raw_rows: list[dict]) -> dict:
    """Parse raw Excel/CSV rows into structured client config fields.
    
    Args:
        raw_rows: List of row dicts from parse_rules_rows_from_uploaded_file()
    
    Returns:
        Dict with: sources, mediums, campaign_types, campaign_notes,
        campaign_examples, medium_source_map — ready to save in ClientConfig.
    """
    fake_config = {"rules_rows": raw_rows}
    
    sources, mediums, campaign_types = extract_client_rule_values(fake_config)
    notes, examples = extract_client_campaign_rule_notes(fake_config)
    medium_source_map = extract_client_medium_source_map(fake_config)
    field_examples = extract_client_field_examples(fake_config)
    
    # Merge field examples into campaign_examples if any
    extra_examples = field_examples.get("campaign_name", [])
    all_examples = list(dict.fromkeys(examples + extra_examples))  # dedup preserving order
    
    return {
        "sources": sources,
        "mediums": mediums,
        "campaign_types": campaign_types,
        "campaign_notes": notes,
        "campaign_examples": all_examples[:20],
        "medium_source_map": medium_source_map,
    }
