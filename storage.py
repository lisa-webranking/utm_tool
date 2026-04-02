"""
Unified storage layer for UTM Governance Tool.

Abstracts all file I/O behind Protocol interfaces so the backend
can be swapped from local JSON files (FileStorage) to PostgreSQL
(future PostgresStorage) without changing app.py or chatbot_ui.py.
"""
import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocols (interfaces)
# ---------------------------------------------------------------------------

@runtime_checkable
class UTMHistoryStore(Protocol):
    def load_all(self) -> list[dict]:
        """Load all history entries."""
        ...

    def load_for_user(self, user_email: str) -> list[dict]:
        """Load history entries for a single user (matched by email hash)."""
        ...

    def upsert(self, entry: dict) -> None:
        """Insert or update (by user_email + property_id + final_url composite key)."""
        ...

    def write_all(self, items: list[dict]) -> None:
        """Overwrite all entries (used by save_utm_history for session cache sync)."""
        ...

    def delete_for_user(self, user_email: str, final_url: str) -> None:
        """Delete a specific entry."""
        ...


@runtime_checkable
class ClientConfigStore(Protocol):
    def load(self, client_id: str) -> Optional[dict]:
        """Load a client config by ID. Returns None if not found."""
        ...

    def save(self, client_id: str, payload: dict) -> None:
        """Create or update a client config."""
        ...

    def list_ids(self) -> list[str]:
        """List all saved client IDs."""
        ...

    def delete(self, client_id: str) -> None:
        """Delete a client config."""
        ...


@runtime_checkable
class CredentialStore(Protocol):
    def save_token(self, user_email: str, creds_json: str) -> None:
        """Persist OAuth token JSON for a user."""
        ...

    def load_token(self, user_email: str) -> Optional[str]:
        """Load OAuth token JSON for a user. Returns None if not found."""
        ...

    def delete_token(self, user_email: str) -> None:
        """Delete persisted OAuth token for a user."""
        ...

    def save_api_key(self, user_email: str, service: str, key: str) -> None:
        """Persist an API key (e.g. Gemini) for a user."""
        ...

    def load_api_key(self, user_email: str, service: str) -> Optional[str]:
        """Load an API key for a user. Returns None if not found."""
        ...


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _email_hash(email: str) -> str:
    """SHA-256 hash of lowercased email for filesystem-safe, privacy-preserving keys."""
    return hashlib.sha256((email or "").strip().lower().encode()).hexdigest()


# ---------------------------------------------------------------------------
# Client config schema validation
# ---------------------------------------------------------------------------

class ClientConfigError(ValueError):
    """Raised when a client config fails validation."""
    pass


@dataclass
class PropertyConfig:
    default_country: str = ""
    expected_domain: str = ""


@dataclass
class ClientConfig:
    """Validated client config. Required: client_id, version, rules_rows."""

    client_id: str = ""
    version: int = 1
    rules_rows: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    updated_by: str = ""
    source_file_name: str = ""
    source_file_sha256: str = ""
    # Optional GA4 fields
    ga4_client_name: str = ""
    ga4_property_id: str = ""
    ga4_property_name: str = ""
    property_config: Optional[PropertyConfig] = None
    # Shared link fields
    shared_link: str = ""
    shared_base_url: str = ""
    shared_link_updated_at: str = ""
    shared_link_updated_by: str = ""
    # Counters
    last_added_rows_count: int = 0
    total_rows_count: int = 0

    @classmethod
    def from_dict(cls, data: dict) -> "ClientConfig":
        """Parse and validate a raw dict. Raises ClientConfigError on problems."""
        if not isinstance(data, dict):
            raise ClientConfigError("Il config non è un dizionario valido")

        cid = str(data.get("client_id", "")).strip()
        if not cid:
            raise ClientConfigError("Manca il campo obbligatorio 'client_id'")

        version = data.get("version", 1)
        try:
            version = int(version)
        except (TypeError, ValueError):
            raise ClientConfigError(f"'version' deve essere un intero, ricevuto: {version!r}")

        rules_rows = data.get("rules_rows")
        if rules_rows is not None and not isinstance(rules_rows, list):
            raise ClientConfigError("'rules_rows' deve essere una lista")

        prop_cfg = data.get("property_config")
        pc = None
        if isinstance(prop_cfg, dict):
            pc = PropertyConfig(
                default_country=str(prop_cfg.get("default_country", "")),
                expected_domain=str(prop_cfg.get("expected_domain", "")),
            )

        return cls(
            client_id=cid,
            version=version,
            rules_rows=rules_rows or [],
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            updated_by=str(data.get("updated_by", "")),
            source_file_name=str(data.get("source_file_name", "")),
            source_file_sha256=str(data.get("source_file_sha256", "")),
            ga4_client_name=str(data.get("ga4_client_name", "")),
            ga4_property_id=str(data.get("ga4_property_id", "")),
            ga4_property_name=str(data.get("ga4_property_name", "")),
            property_config=pc,
            shared_link=str(data.get("shared_link", "")),
            shared_base_url=str(data.get("shared_base_url", "")),
            shared_link_updated_at=str(data.get("shared_link_updated_at", "")),
            shared_link_updated_by=str(data.get("shared_link_updated_by", "")),
            last_added_rows_count=int(data.get("last_added_rows_count", 0) or 0),
            total_rows_count=int(data.get("total_rows_count", 0) or 0),
        )

    def validate(self) -> list[str]:
        """Return list of warning strings (non-fatal issues)."""
        warnings = []
        if not self.rules_rows:
            warnings.append("rules_rows è vuoto — il chatbot non avrà regole cliente")
        if self.version < 1:
            warnings.append(f"version={self.version} sembra invalido (atteso >= 1)")
        return warnings


def validate_client_config(data: dict) -> tuple[ClientConfig, list[str]]:
    """Validate a raw dict. Returns (parsed config, warnings). Raises ClientConfigError on fatal issues."""
    cfg = ClientConfig.from_dict(data)
    warnings = cfg.validate()
    return cfg, warnings


# ---------------------------------------------------------------------------
# FileStorage implementations
# ---------------------------------------------------------------------------

class FileUTMHistoryStore:
    """UTM history backed by a single JSON file."""

    def __init__(self, path: Path):
        self._path = path

    def _read_all(self) -> list[dict]:
        try:
            if self._path.exists():
                raw = self._path.read_text(encoding="utf-8").strip()
                loaded = json.loads(raw) if raw else []
                if isinstance(loaded, list):
                    return [x for x in loaded if isinstance(x, dict)]
        except Exception:
            logger.exception("FileUTMHistoryStore: failed to read %s", self._path)
        return []

    def write_all(self, items: list[dict]) -> None:
        safe = [x for x in (items or []) if isinstance(x, dict)]
        try:
            self._path.write_text(
                json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            logger.exception("FileUTMHistoryStore: failed to write %s", self._path)

    def load_all(self) -> list[dict]:
        return self._read_all()

    def load_for_user(self, user_email: str) -> list[dict]:
        target = _email_hash(user_email)
        items = self._read_all()
        return [
            x for x in items
            if _email_hash(x.get("user_email", "")) == target
        ]

    def upsert(self, entry: dict) -> None:
        items = self._read_all()
        key_fields = ("user_email", "property_id", "final_url")
        idx = next(
            (i for i, x in enumerate(items)
             if all(x.get(k) == entry.get(k) for k in key_fields)),
            None,
        )
        if idx is None:
            items.append(entry)
        else:
            items[idx].update(entry)
        self.write_all(items)

    def delete_for_user(self, user_email: str, final_url: str) -> None:
        items = self._read_all()
        items = [
            x for x in items
            if not (x.get("user_email") == user_email and x.get("final_url") == final_url)
        ]
        self.write_all(items)


class FileClientConfigStore:
    """Client configs backed by individual JSON files in a directory."""

    def __init__(self, config_dir: Path):
        self._dir = config_dir

    def _path_for(self, client_id: str) -> Path:
        from utm_normalize import normalize_client_id
        return self._dir / f"{normalize_client_id(client_id)}.json"

    def load(self, client_id: str) -> Optional[dict]:
        from utm_normalize import normalize_client_id
        cid = normalize_client_id(client_id)
        if not cid:
            return None
        path = self._path_for(cid)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return None
            # Validate schema — log warnings but don't block loading
            try:
                _cfg, warnings = validate_client_config(payload)
                for w in warnings:
                    logger.warning("Client config '%s': %s", cid, w)
            except ClientConfigError as e:
                logger.error("Client config '%s' validation failed: %s", cid, e)
            return payload
        except Exception:
            logger.exception("FileClientConfigStore: failed to load %s", path)
            return None

    def save(self, client_id: str, payload: dict) -> None:
        from utm_normalize import normalize_client_id
        cid = normalize_client_id(client_id)
        if not cid:
            raise ValueError("client_id non valido")
        body = dict(payload or {})
        body["client_id"] = cid
        # Validate before writing — raises ClientConfigError on fatal issues
        validate_client_config(body)
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._path_for(cid)
        path.write_text(
            json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def list_ids(self) -> list[str]:
        self._dir.mkdir(parents=True, exist_ok=True)
        return sorted({p.stem for p in self._dir.glob("*.json")})

    def delete(self, client_id: str) -> None:
        path = self._path_for(client_id)
        if path.exists():
            path.unlink()


class FileCredentialStore:
    """OAuth tokens and API keys backed by per-user JSON files."""

    def __init__(self, tokens_dir: Path, api_keys_path: Path):
        self._tokens_dir = tokens_dir
        self._api_keys_path = api_keys_path

    def _token_path(self, user_email: str) -> Path:
        return self._tokens_dir / f"{_email_hash(user_email)}.json"

    def save_token(self, user_email: str, creds_json: str) -> None:
        try:
            self._tokens_dir.mkdir(parents=True, exist_ok=True)
            self._token_path(user_email).write_text(creds_json, encoding="utf-8")
        except Exception:
            logger.exception("FileCredentialStore: failed to save token for %s", _email_hash(user_email))

    def load_token(self, user_email: str) -> Optional[str]:
        path = self._token_path(user_email)
        if not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            logger.exception("FileCredentialStore: failed to load token")
            return None

    def delete_token(self, user_email: str) -> None:
        path = self._token_path(user_email)
        try:
            if path.exists():
                path.unlink()
        except Exception:
            logger.exception("FileCredentialStore: failed to delete token")

    # --- API keys ---

    def _load_api_keys(self) -> dict:
        try:
            if self._api_keys_path.exists():
                return json.loads(self._api_keys_path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("FileCredentialStore: failed to read api_keys")
        return {}

    def _save_api_keys(self, data: dict) -> None:
        try:
            self._api_keys_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            logger.exception("FileCredentialStore: failed to write api_keys")

    def save_api_key(self, user_email: str, service: str, key: str) -> None:
        data = self._load_api_keys()
        eh = _email_hash(user_email)
        data.setdefault(eh, {})[service] = key
        self._save_api_keys(data)

    def load_api_key(self, user_email: str, service: str) -> Optional[str]:
        data = self._load_api_keys()
        return data.get(_email_hash(user_email), {}).get(service)


# ---------------------------------------------------------------------------
# PostgresStorage implementations
# ---------------------------------------------------------------------------

_pg_pool = None


def _get_pg_connection(dsn: str):
    """Get a connection from the pool. Caller must call _put_pg_connection() to return it."""
    global _pg_pool
    if _pg_pool is None:
        from psycopg2 import pool as _pool
        _pg_pool = _pool.ThreadedConnectionPool(minconn=1, maxconn=10, dsn=dsn)
        logger.info("PostgreSQL connection pool created (1-10 connections)")
    return _pg_pool.getconn()


def _put_pg_connection(conn) -> None:
    """Return a connection to the pool instead of closing it."""
    if _pg_pool is not None:
        _pg_pool.putconn(conn)
    else:
        conn.close()


class PostgresUTMHistoryStore:
    """UTM history backed by PostgreSQL."""

    def __init__(self, dsn: str):
        self._dsn = dsn

    def load_all(self) -> list[dict]:
        conn = _get_pg_connection(self._dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT user_email, user_email_hash, client_id, property_id, "
                    "property_name, final_url, utm_source, utm_medium, utm_campaign, "
                    "campaign_name, live_date, expected_channel, tracking_status, created_at "
                    "FROM utm_history ORDER BY created_at DESC"
                )
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            _put_pg_connection(conn)

    def load_for_user(self, user_email: str) -> list[dict]:
        eh = _email_hash(user_email)
        conn = _get_pg_connection(self._dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT user_email, user_email_hash, client_id, property_id, "
                    "property_name, final_url, utm_source, utm_medium, utm_campaign, "
                    "campaign_name, live_date, expected_channel, tracking_status, created_at "
                    "FROM utm_history WHERE user_email_hash = %s ORDER BY created_at DESC",
                    (eh,),
                )
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            _put_pg_connection(conn)

    def upsert(self, entry: dict) -> None:
        eh = _email_hash(entry.get("user_email", ""))
        conn = _get_pg_connection(self._dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO utm_history "
                    "(user_email_hash, user_email, client_id, property_id, property_name, "
                    " final_url, utm_source, utm_medium, utm_campaign, campaign_name, "
                    " live_date, expected_channel, tracking_status, created_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW()) "
                    "ON CONFLICT (user_email_hash, property_id, final_url) DO UPDATE SET "
                    " utm_source=EXCLUDED.utm_source, utm_medium=EXCLUDED.utm_medium, "
                    " utm_campaign=EXCLUDED.utm_campaign, campaign_name=EXCLUDED.campaign_name, "
                    " live_date=EXCLUDED.live_date, expected_channel=EXCLUDED.expected_channel, "
                    " tracking_status=EXCLUDED.tracking_status",
                    (
                        eh, entry.get("user_email", ""), entry.get("client_id", ""),
                        entry.get("property_id", ""), entry.get("property_name", ""),
                        entry.get("final_url", ""), entry.get("utm_source", ""),
                        entry.get("utm_medium", ""), entry.get("utm_campaign", ""),
                        entry.get("campaign_name", ""), entry.get("live_date", ""),
                        entry.get("expected_channel_group", ""),
                        entry.get("tracking_status", "pending"),
                    ),
                )
            conn.commit()
        finally:
            _put_pg_connection(conn)

    def write_all(self, items: list[dict]) -> None:
        """Replace all entries. Used for bulk sync from session cache."""
        conn = _get_pg_connection(self._dsn)
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM utm_history")
                for entry in items:
                    if not isinstance(entry, dict):
                        continue
                    eh = _email_hash(entry.get("user_email", ""))
                    cur.execute(
                        "INSERT INTO utm_history "
                        "(user_email_hash, user_email, client_id, property_id, property_name, "
                        " final_url, utm_source, utm_medium, utm_campaign, campaign_name, "
                        " live_date, expected_channel, tracking_status, created_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())",
                        (
                            eh, entry.get("user_email", ""), entry.get("client_id", ""),
                            entry.get("property_id", ""), entry.get("property_name", ""),
                            entry.get("final_url", ""), entry.get("utm_source", ""),
                            entry.get("utm_medium", ""), entry.get("utm_campaign", ""),
                            entry.get("campaign_name", ""), entry.get("live_date", ""),
                            entry.get("expected_channel_group", ""),
                            entry.get("tracking_status", "pending"),
                        ),
                    )
            conn.commit()
        finally:
            _put_pg_connection(conn)

    def delete_for_user(self, user_email: str, final_url: str) -> None:
        eh = _email_hash(user_email)
        conn = _get_pg_connection(self._dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM utm_history WHERE user_email_hash = %s AND final_url = %s",
                    (eh, final_url),
                )
            conn.commit()
        finally:
            _put_pg_connection(conn)


class PostgresClientConfigStore:
    """Client configs backed by PostgreSQL JSONB."""

    def __init__(self, dsn: str):
        self._dsn = dsn

    def load(self, client_id: str) -> Optional[dict]:
        from utm_normalize import normalize_client_id
        cid = normalize_client_id(client_id)
        if not cid:
            return None
        conn = _get_pg_connection(self._dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT config_json FROM client_configs WHERE client_id = %s", (cid,)
                )
                row = cur.fetchone()
                if not row:
                    return None
                payload = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                try:
                    _cfg, warnings = validate_client_config(payload)
                    for w in warnings:
                        logger.warning("Client config '%s': %s", cid, w)
                except ClientConfigError as e:
                    logger.error("Client config '%s' validation failed: %s", cid, e)
                return payload
        finally:
            _put_pg_connection(conn)

    def save(self, client_id: str, payload: dict) -> None:
        from utm_normalize import normalize_client_id
        cid = normalize_client_id(client_id)
        if not cid:
            raise ValueError("client_id non valido")
        body = dict(payload or {})
        body["client_id"] = cid
        validate_client_config(body)
        conn = _get_pg_connection(self._dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO client_configs (client_id, version, config_json, updated_at) "
                    "VALUES (%s, %s, %s, NOW()) "
                    "ON CONFLICT (client_id) DO UPDATE SET "
                    " version = EXCLUDED.version, config_json = EXCLUDED.config_json, "
                    " updated_at = NOW()",
                    (cid, body.get("version", 1), json.dumps(body, ensure_ascii=False)),
                )
            conn.commit()
        finally:
            _put_pg_connection(conn)

    def list_ids(self) -> list[str]:
        conn = _get_pg_connection(self._dsn)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT client_id FROM client_configs ORDER BY client_id")
                return [row[0] for row in cur.fetchall()]
        finally:
            _put_pg_connection(conn)

    def delete(self, client_id: str) -> None:
        from utm_normalize import normalize_client_id
        cid = normalize_client_id(client_id)
        conn = _get_pg_connection(self._dsn)
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM client_configs WHERE client_id = %s", (cid,))
            conn.commit()
        finally:
            _put_pg_connection(conn)


class PostgresCredentialStore:
    """OAuth tokens and API keys backed by PostgreSQL."""

    def __init__(self, dsn: str):
        self._dsn = dsn

    def _ensure_user(self, cur, user_email: str) -> int:
        """Get or create user row, return user_id."""
        eh = _email_hash(user_email)
        cur.execute("SELECT id FROM users WHERE email_hash = %s", (eh,))
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute(
            "INSERT INTO users (email_hash) VALUES (%s) RETURNING id", (eh,)
        )
        return cur.fetchone()[0]

    def save_token(self, user_email: str, creds_json: str) -> None:
        conn = _get_pg_connection(self._dsn)
        try:
            with conn.cursor() as cur:
                uid = self._ensure_user(cur, user_email)
                cur.execute(
                    "INSERT INTO credentials (user_id, provider, token_json, updated_at) "
                    "VALUES (%s, 'google', %s, NOW()) "
                    "ON CONFLICT (user_id, provider) DO UPDATE SET "
                    " token_json = EXCLUDED.token_json, updated_at = NOW()",
                    (uid, creds_json),
                )
            conn.commit()
        finally:
            _put_pg_connection(conn)

    def load_token(self, user_email: str) -> Optional[str]:
        eh = _email_hash(user_email)
        conn = _get_pg_connection(self._dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT c.token_json FROM credentials c "
                    "JOIN users u ON c.user_id = u.id "
                    "WHERE u.email_hash = %s AND c.provider = 'google'",
                    (eh,),
                )
                row = cur.fetchone()
                return row[0] if row else None
        finally:
            _put_pg_connection(conn)

    def delete_token(self, user_email: str) -> None:
        eh = _email_hash(user_email)
        conn = _get_pg_connection(self._dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM credentials WHERE user_id IN "
                    "(SELECT id FROM users WHERE email_hash = %s) AND provider = 'google'",
                    (eh,),
                )
            conn.commit()
        finally:
            _put_pg_connection(conn)

    def save_api_key(self, user_email: str, service: str, key: str) -> None:
        conn = _get_pg_connection(self._dsn)
        try:
            with conn.cursor() as cur:
                uid = self._ensure_user(cur, user_email)
                cur.execute(
                    "INSERT INTO api_keys (user_id, service, encrypted_key, updated_at) "
                    "VALUES (%s, %s, %s, NOW()) "
                    "ON CONFLICT (user_id, service) DO UPDATE SET "
                    " encrypted_key = EXCLUDED.encrypted_key, updated_at = NOW()",
                    (uid, service, key),
                )
            conn.commit()
        finally:
            _put_pg_connection(conn)

    def load_api_key(self, user_email: str, service: str) -> Optional[str]:
        eh = _email_hash(user_email)
        conn = _get_pg_connection(self._dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT a.encrypted_key FROM api_keys a "
                    "JOIN users u ON a.user_id = u.id "
                    "WHERE u.email_hash = %s AND a.service = %s",
                    (eh, service),
                )
                row = cur.fetchone()
                return row[0] if row else None
        finally:
            _put_pg_connection(conn)


# ---------------------------------------------------------------------------
# Factory — single point to get all stores
# ---------------------------------------------------------------------------

def create_file_stores(base_dir: Path) -> tuple[
    FileUTMHistoryStore, FileClientConfigStore, FileCredentialStore
]:
    """Create all file-based stores rooted at base_dir (typically app.py's parent)."""
    return (
        FileUTMHistoryStore(base_dir / "utm_history.json"),
        FileClientConfigStore(base_dir / "client_configs"),
        FileCredentialStore(
            tokens_dir=base_dir / "tokens",
            api_keys_path=base_dir / "api_keys.json",
        ),
    )


def create_postgres_stores(dsn: str) -> tuple[
    PostgresUTMHistoryStore, PostgresClientConfigStore, PostgresCredentialStore
]:
    """Create all PostgreSQL-backed stores."""
    return (
        PostgresUTMHistoryStore(dsn),
        PostgresClientConfigStore(dsn),
        PostgresCredentialStore(dsn),
    )


def create_stores(base_dir: Path):
    """Auto-select storage backend based on DATABASE_URL env var.

    If DATABASE_URL is set, uses PostgreSQL. Otherwise, uses local JSON files.
    """
    import os
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if dsn:
        logger.info("Using PostgreSQL storage backend")
        return create_postgres_stores(dsn)
    logger.info("Using file-based storage backend")
    return create_file_stores(base_dir)
