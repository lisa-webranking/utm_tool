"""
Unified UTM value normalization.

All UTM normalization logic lives here to ensure consistency
between the builder (app.py) and the chatbot (chatbot_ui.py).
"""
import re
from slugify import slugify


def normalize_token(text: str) -> str:
    """Normalize a generic UTM token (source, campaign, content, term).

    Uses slugify: lowercase, hyphens as separator.
    Example: "Saldi Invernali 2026" -> "saldi-invernali-2026"
    """
    if not text:
        return ""
    return slugify(text, separator="-", lowercase=True)


def normalize_medium_token(text: str) -> str:
    """Normalize utm_medium preserving underscores for GA4 conventions.

    Example: "social paid" -> "social_paid", "Social-Paid" -> "social_paid"
    """
    if not text:
        return ""
    value = str(text).strip().lower()
    value = value.replace("-", "_")
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"[^a-z0-9_-]", "", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value


def sanitize_utm_value(value: str) -> str:
    """Sanitize a UTM value for chatbot context extraction.

    Lowercase, spaces to underscores, strips special chars.
    Example: "Facebook Ads!" -> "facebook_ads"
    """
    if value is None:
        return ""
    v = str(value).strip().lower()
    v = v.replace(" ", "_")
    v = re.sub(r"[^\w-]", "_", v)
    v = re.sub(r"_+", "_", v).strip("_")
    return v


def normalize_client_id(value: str) -> str:
    """Normalize a client ID for filesystem-safe usage.

    Example: "Chicco 2023" -> "chicco_2023"
    """
    return slugify((value or "").strip(), separator="_")


def suggest_naming_value(text: str, prefer_hyphen: bool = True) -> str:
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


def validate_naming_rules(text: str, prefer_hyphen: bool = True) -> tuple:
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
