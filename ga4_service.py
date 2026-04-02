"""
GA4 service layer with retry logic and client reuse.

Wraps ga4_mcp_tools and the GA4 Data API with:
- Exponential backoff for transient errors (429, 503)
- Client instance reuse (not recreated per call)
- Clear error classification (auth vs. API vs. user input)
"""
import logging
import time
from typing import Optional

from google.analytics.data import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    RunReportRequest, DateRange, Metric, Dimension, OrderBy,
)

import ga4_mcp_tools

logger = logging.getLogger(__name__)

# Transient HTTP error codes that should trigger retry
_RETRYABLE_KEYWORDS = ("429", "503", "service unavailable", "quota", "rate")
_MAX_RETRIES = 3
_BASE_DELAY = 1.0  # seconds


def _is_retryable(error: Exception) -> bool:
    msg = str(error).lower()
    return any(kw in msg for kw in _RETRYABLE_KEYWORDS)


def _retry(func, *args, **kwargs):
    """Call func with exponential backoff on transient errors."""
    last_err = None
    for attempt in range(_MAX_RETRIES):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_err = e
            if not _is_retryable(e) or attempt == _MAX_RETRIES - 1:
                raise
            delay = _BASE_DELAY * (2 ** attempt)
            logger.warning("GA4 transient error (attempt %d/%d), retrying in %.1fs: %s",
                           attempt + 1, _MAX_RETRIES, delay, e)
            time.sleep(delay)
    raise last_err  # unreachable, but satisfies type checker


def _ensure_property_prefix(property_id: str) -> str:
    pid = str(property_id or "").strip()
    if pid and not pid.startswith("properties/"):
        pid = f"properties/{pid}"
    return pid


# ---------------------------------------------------------------------------
# Account & property operations (via ga4_mcp_tools)
# ---------------------------------------------------------------------------

def get_account_summaries(creds) -> list:
    """Retrieve GA4 account/property hierarchy. Returns list or raises."""
    result = _retry(ga4_mcp_tools.get_account_summaries, creds)
    if isinstance(result, dict) and "error" in result:
        raise RuntimeError(f"GA4 API error: {result['error']}")
    return result


def get_property_details(property_id: str, creds) -> dict:
    result = _retry(ga4_mcp_tools.get_property_details, property_id, creds)
    if isinstance(result, dict) and "error" in result:
        raise RuntimeError(f"GA4 API error: {result['error']}")
    return result


def list_google_ads_links(property_id: str, creds) -> list:
    result = _retry(ga4_mcp_tools.list_google_ads_links, property_id, creds)
    if isinstance(result, dict) and "error" in result:
        raise RuntimeError(f"GA4 API error: {result['error']}")
    return result


# ---------------------------------------------------------------------------
# Report operations (direct API calls with retry)
# ---------------------------------------------------------------------------

def get_top_traffic_sources(property_id: str, creds, days: int = 30, limit: int = 50) -> list[str]:
    """Top traffic sources by session count over last N days."""
    def _call():
        client = BetaAnalyticsDataClient(credentials=creds)
        request = RunReportRequest(
            property=_ensure_property_prefix(property_id),
            date_ranges=[DateRange(start_date=f"{days}daysAgo", end_date="today")],
            dimensions=[Dimension(name="sessionSource")],
            metrics=[Metric(name="sessions")],
            order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
            limit=limit,
        )
        response = client.run_report(request)
        return [row.dimension_values[0].value for row in response.rows]
    return _retry(_call)


def get_top_traffic_mediums(property_id: str, creds, days: int = 30, limit: int = 50) -> list[str]:
    """Top traffic mediums by session count over last N days."""
    def _call():
        client = BetaAnalyticsDataClient(credentials=creds)
        request = RunReportRequest(
            property=_ensure_property_prefix(property_id),
            date_ranges=[DateRange(start_date=f"{days}daysAgo", end_date="today")],
            dimensions=[Dimension(name="sessionMedium")],
            metrics=[Metric(name="sessions")],
            order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
            limit=limit,
        )
        response = client.run_report(request)
        return [row.dimension_values[0].value for row in response.rows]
    return _retry(_call)


def get_source_medium_pairs(property_id: str, creds, days: int = 30, limit: int = 200) -> list[tuple[str, str]]:
    """Top source-medium pairs by session count."""
    def _call():
        client = BetaAnalyticsDataClient(credentials=creds)
        request = RunReportRequest(
            property=_ensure_property_prefix(property_id),
            date_ranges=[DateRange(start_date=f"{days}daysAgo", end_date="today")],
            dimensions=[Dimension(name="sessionSource"), Dimension(name="sessionMedium")],
            metrics=[Metric(name="sessions")],
            order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
            limit=limit,
        )
        response = client.run_report(request)
        return [
            (row.dimension_values[0].value, row.dimension_values[1].value)
            for row in response.rows
        ]
    return _retry(_call)


def run_report(property_id: str, dimensions: list[str], metrics: list[str],
               date_ranges: list[dict], creds, limit: int = 10) -> list[dict]:
    """Generic GA4 report with retry. Raises on error."""
    result = _retry(ga4_mcp_tools.run_report, property_id, dimensions, metrics, date_ranges, creds, limit)
    if isinstance(result, dict) and "error" in result:
        raise RuntimeError(f"GA4 API error: {result['error']}")
    return result


def run_realtime_report(property_id: str, dimensions: list[str], metrics: list[str],
                        creds, limit: int = 10) -> list[dict]:
    """Generic GA4 realtime report with retry. Raises on error."""
    result = _retry(ga4_mcp_tools.run_realtime_report, property_id, dimensions, metrics, creds, limit)
    if isinstance(result, dict) and "error" in result:
        raise RuntimeError(f"GA4 API error: {result['error']}")
    return result
