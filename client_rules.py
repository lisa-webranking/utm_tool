"""
Client config rule access and campaign validation logic.

With the relational data model, extract_* functions are simple accessors
(the parsing from Excel happens at upload time, not at read time).
"""
import re
from datetime import datetime, timedelta
from utm_normalize import normalize_token, normalize_medium_token


def order_by_ga4_priority(options, ga4_priority, normalizer):
    """Order options by GA4 popularity (sessions) first, then alphabetical fallback."""
    values = []
    seen = set()
    for raw in options or []:
        v = normalizer(raw)
        if v and v not in seen:
            values.append(v)
            seen.add(v)

    if not ga4_priority:
        return sorted(values, key=str.lower)

    priority_tokens = []
    for p in ga4_priority:
        pt = normalizer(p)
        if pt and pt in seen:
            priority_tokens.append(pt)
    rest = [v for v in values if v not in set(priority_tokens)]
    return priority_tokens + sorted(rest, key=str.lower)


# ---------------------------------------------------------------------------
# Client config accessors (data is already structured, no parsing needed)
# ---------------------------------------------------------------------------

def extract_client_rule_values(client_config: dict):
    """Return (sources, mediums, campaign_types) from a client config."""
    if not client_config:
        return [], [], []
    sources = sorted(set(client_config.get("sources", [])))
    mediums = sorted(set(client_config.get("mediums", [])))
    campaign_types = sorted(set(client_config.get("campaign_types", [])))
    return sources, mediums, campaign_types


def extract_client_field_examples(client_config: dict) -> dict:
    """Return dict of field → example values."""
    if not client_config:
        return {}
    return {
        "campaign_name": client_config.get("campaign_examples", []),
        "campaign_type": client_config.get("campaign_types", []),
        "country_language": [client_config.get("default_country", "")] if client_config.get("default_country") else [],
    }


def build_placeholder_examples(values, fallback: str, limit: int = 3) -> str:
    """Format sample values as comma-separated string."""
    cleaned = [str(v).strip() for v in (values or []) if str(v).strip()]
    return ", ".join(cleaned[:limit]) if cleaned else fallback


def extract_client_campaign_rule_notes(client_config: dict):
    """Return (notes, examples) from a client config."""
    if not client_config:
        return [], []
    notes = list(client_config.get("campaign_notes", []))
    examples = list(client_config.get("campaign_examples", []))
    return notes, examples


def extract_client_medium_source_map(client_config: dict) -> dict:
    """Return {medium: [sources]} mapping."""
    if not client_config:
        return {}
    return dict(client_config.get("medium_source_map", {}))


# ---------------------------------------------------------------------------
# Build chatbot context text from structured config
# ---------------------------------------------------------------------------

def build_client_rules_text(client_config: dict) -> str:
    """Format client config as text for the chatbot system prompt."""
    if not client_config:
        return ""
    cid = client_config.get("client_id", "")
    sources = client_config.get("sources", [])
    mediums = client_config.get("mediums", [])
    campaign_types = client_config.get("campaign_types", [])
    msm = client_config.get("medium_source_map", {})
    notes = client_config.get("campaign_notes", [])
    examples = client_config.get("campaign_examples", [])
    version = client_config.get("version", 0)
    updated_at = client_config.get("updated_at", "")

    lines = [f"- client_id: {cid}"]
    if version:
        lines.append(f"- config_version: {version}")
    if updated_at:
        lines.append(f"- config_updated_at: {updated_at}")
    if client_config.get("ga4_client_name"):
        lines.append(f"- cliente GA4: {client_config['ga4_client_name']}")
    if sources:
        lines.append(f"- utm_source consentiti (esempi): {', '.join(sources[:15])}")
    if mediums:
        lines.append(f"- utm_medium consentiti (esempi): {', '.join(mediums[:15])}")
    if campaign_types:
        lines.append(f"- campaign_type usati: {', '.join(campaign_types[:10])}")
    for medium, src_list in msm.items():
        if src_list:
            lines.append(f"- mapping utm_source per utm_medium={medium}: {', '.join(src_list[:10])}")
    for note in notes[:4]:
        lines.append(f"- regola utm_campaign cliente: {note}")
    for ex in examples[:5]:
        lines.append(f"- esempio utm_campaign cliente: {ex}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Date / week helpers
# ---------------------------------------------------------------------------

def get_last_full_week_range(reference_date=None):
    today = reference_date or datetime.today().date()
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_sunday = last_monday + timedelta(days=6)
    return last_monday, last_sunday


def is_monday(reference_date=None):
    today = reference_date or datetime.today().date()
    return today.weekday() == 0


# ---------------------------------------------------------------------------
# Campaign validation
# ---------------------------------------------------------------------------

def validate_campaign_value_against_client_rules(raw_campaign: str, client_config: dict):
    """Validate a utm_campaign value against client rules. Returns (issues, suggestions)."""
    issues = []
    suggestions = []
    if not client_config or not raw_campaign:
        return issues, suggestions

    campaign = str(raw_campaign).strip().lower()
    campaign_types = set(client_config.get("campaign_types", []))
    parts = campaign.split("_")

    if len(parts) < 3:
        issues.append("utm_campaign dovrebbe avere almeno 3 token separati da underscore (es. country_type_name)")
    if campaign_types and len(parts) >= 2:
        ctype = normalize_token(parts[1])
        if ctype and ctype not in campaign_types:
            issues.append(f"campaign_type '{ctype}' non è tra quelli consentiti: {', '.join(sorted(campaign_types)[:8])}")
            suggestions.append(f"Usa uno tra: {', '.join(sorted(campaign_types)[:8])}")

    return issues, suggestions


def audit_ga4_campaign_entry(
    session_source: str, session_medium: str, session_campaign: str,
    observed_channel: str, client_config: dict
):
    """Cross-validate a GA4 session entry against client rules. Returns dict with status and issues."""
    issues = []
    if not client_config:
        return {"status": "skip", "issues": issues}

    sources = set(client_config.get("sources", []))
    mediums = set(client_config.get("mediums", []))
    msm = client_config.get("medium_source_map", {})

    src = normalize_token(session_source)
    med = normalize_medium_token(session_medium)

    if sources and src and src not in sources:
        issues.append(f"utm_source '{src}' non è tra i valori consentiti")
    if mediums and med and med not in mediums:
        issues.append(f"utm_medium '{med}' non è tra i valori consentiti")
    if msm and med in msm:
        allowed_sources = set(msm[med])
        if src and allowed_sources and src not in allowed_sources:
            issues.append(f"utm_source '{src}' non è mappato a utm_medium '{med}' (attesi: {', '.join(sorted(allowed_sources)[:5])})")

    cmp_issues, _ = validate_campaign_value_against_client_rules(session_campaign, client_config)
    issues.extend(cmp_issues)

    status = "ok" if not issues else "warning"
    return {"status": status, "issues": issues}
