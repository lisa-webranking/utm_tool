from typing import Any, Dict, List, Optional


def normalize_property_id(property_id: str) -> str:
    return str(property_id or "").replace("properties/", "").strip()


def normalize_ga4_scope(scope: str) -> str:
    val = str(scope or "").strip().lower()
    if val in {"single_property", "multi_property", "account_only", "none"}:
        return val
    return ""


def normalize_allowed_properties(items: Any) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    seen = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        pid = normalize_property_id(item.get("property_id", ""))
        pname = str(item.get("property_name", "")).strip()
        if not pid or pid in seen:
            continue
        normalized.append({"property_id": pid, "property_name": pname})
        seen.add(pid)
    return normalized


def _extract_properties(accounts_structure: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    flat = []
    for account in accounts_structure or []:
        account_name = str(account.get("display_name", "")).strip()
        for prop in account.get("properties", []) or []:
            pid = normalize_property_id(prop.get("property_id", ""))
            pname = str(prop.get("display_name", "")).strip()
            if pid:
                flat.append(
                    {
                        "account_name": account_name,
                        "property_id": pid,
                        "property_name": pname,
                    }
                )
    return flat


def _find_property(accounts_structure: List[Dict[str, Any]], property_id: str) -> Dict[str, str]:
    target = normalize_property_id(property_id)
    if not target:
        return {}
    for item in _extract_properties(accounts_structure):
        if item.get("property_id") == target:
            return item
    return {}


def build_ga4_binding_state(
    *,
    lock_mode: bool,
    accounts_structure: List[Dict[str, Any]],
    configured_scope: str = "",
    configured_property_id: str = "",
    configured_property_name: str = "",
    configured_account_name: str = "",
    configured_allowed_properties: Optional[List[Dict[str, str]]] = None,
    configured_default_property_id: str = "",
    selected_property_id: str = "",
    selected_property_name: str = "",
) -> Dict[str, Any]:
    cfg_scope = normalize_ga4_scope(configured_scope)
    cfg_pid = normalize_property_id(configured_property_id)
    cfg_pname = str(configured_property_name or "").strip()
    cfg_aname = str(configured_account_name or "").strip()
    cfg_allowed = normalize_allowed_properties(configured_allowed_properties)
    cfg_default_pid = normalize_property_id(configured_default_property_id)
    sel_pid = normalize_property_id(selected_property_id)
    sel_pname = str(selected_property_name or "").strip()

    if not cfg_scope:
        if cfg_allowed and len(cfg_allowed) > 1:
            cfg_scope = "multi_property"
        elif cfg_pid or cfg_allowed:
            cfg_scope = "single_property"
        elif cfg_aname:
            cfg_scope = "account_only"
        else:
            cfg_scope = "none"

    if not cfg_allowed and cfg_pid:
        cfg_allowed = [{"property_id": cfg_pid, "property_name": cfg_pname}]
    if not cfg_default_pid:
        cfg_default_pid = cfg_pid or (cfg_allowed[0]["property_id"] if cfg_allowed else "")

    allowed_ids = {p["property_id"] for p in cfg_allowed}
    is_selection_allowed = (not sel_pid) or (not allowed_ids) or (sel_pid in allowed_ids)

    if lock_mode:
        if cfg_scope in {"none", "account_only"}:
            effective_pid = sel_pid
            effective_name = sel_pname
        elif sel_pid and is_selection_allowed:
            effective_pid = sel_pid
            effective_name = sel_pname
        else:
            effective_pid = cfg_default_pid
            effective_name = cfg_pname
    else:
        effective_pid = sel_pid
        effective_name = sel_pname

    found = _find_property(accounts_structure, effective_pid) if effective_pid else {}
    resolved_account = str(found.get("account_name", "")).strip()
    resolved_name = str(found.get("property_name", "")).strip()
    is_accessible = bool(found)

    if lock_mode and cfg_scope == "none" and not sel_pid:
        reason = "manual_property_required_for_none_scope"
    elif lock_mode and cfg_scope == "account_only" and not sel_pid:
        reason = "manual_property_required_for_account_scope"
    elif lock_mode and cfg_scope in {"single_property", "multi_property"} and not cfg_allowed:
        reason = "missing_configured_property"
    elif lock_mode and cfg_scope == "multi_property" and sel_pid and not is_selection_allowed:
        reason = "selected_property_not_allowed"
    elif lock_mode and effective_pid and not is_accessible:
        reason = "configured_property_not_accessible"
    elif not lock_mode and not sel_pid:
        reason = "property_not_selected"
    elif not lock_mode and sel_pid and not is_accessible:
        reason = "selected_property_not_accessible"
    else:
        reason = "ok"

    return {
        "lock_mode": bool(lock_mode),
        "ga4_scope": cfg_scope,
        "configured_default_property_id": cfg_default_pid,
        "configured_allowed_properties": cfg_allowed,
        "allowed_property_ids": [p["property_id"] for p in cfg_allowed],
        "configured_property_id": cfg_pid,
        "configured_property_name": cfg_pname,
        "configured_account_name": cfg_aname,
        "effective_property_id": effective_pid,
        "effective_property_name": effective_name or resolved_name,
        "resolved_property_name": resolved_name,
        "resolved_account_name": resolved_account,
        "is_accessible": bool(is_accessible),
        "is_selected_allowed": bool(is_selection_allowed),
        "reason": reason,
    }
