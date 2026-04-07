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
class ClientConfig:
    """Relational client config — no JSON blobs.

    Arrays (sources, mediums, etc.) are stored as TEXT[] in PostgreSQL
    or as JSON lists in the file-based fallback.
    The medium→source mapping is a separate table / nested dict.
    """

    client_id: str = ""
    version: int = 1
    # GA4 link
    ga4_property_id: str = ""
    ga4_property_name: str = ""
    ga4_client_name: str = ""
    # Defaults
    default_country: str = ""
    expected_domain: str = ""
    # Allowed UTM values
    sources: list[str] = field(default_factory=list)
    mediums: list[str] = field(default_factory=list)
    campaign_types: list[str] = field(default_factory=list)
    # Campaign naming rules
    campaign_notes: list[str] = field(default_factory=list)
    campaign_examples: list[str] = field(default_factory=list)
    # Medium → source mapping (dict of medium → list of sources)
    medium_source_map: dict[str, list[str]] = field(default_factory=dict)
    # Shared link
    shared_link: str = ""
    shared_base_url: str = ""
    # Upload tracking
    source_file_name: str = ""
    source_file_sha256: str = ""
    # Audit
    updated_by: str = ""
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "ClientConfig":
        """Parse and validate a raw dict. Raises ClientConfigError on fatal issues."""
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

        def _str_list(val) -> list[str]:
            if isinstance(val, list):
                return [str(v) for v in val if str(v).strip()]
            return []

        msm_raw = data.get("medium_source_map", {})
        msm = {}
        if isinstance(msm_raw, dict):
            for k, v in msm_raw.items():
                msm[str(k)] = _str_list(v) if isinstance(v, list) else []

        return cls(
            client_id=cid,
            version=version,
            ga4_property_id=str(data.get("ga4_property_id", "")),
            ga4_property_name=str(data.get("ga4_property_name", "")),
            ga4_client_name=str(data.get("ga4_client_name", "")),
            default_country=str(data.get("default_country", "")),
            expected_domain=str(data.get("expected_domain", "")),
            sources=_str_list(data.get("sources")),
            mediums=_str_list(data.get("mediums")),
            campaign_types=_str_list(data.get("campaign_types")),
            campaign_notes=_str_list(data.get("campaign_notes")),
            campaign_examples=_str_list(data.get("campaign_examples")),
            medium_source_map=msm,
            shared_link=str(data.get("shared_link", "")),
            shared_base_url=str(data.get("shared_base_url", "")),
            source_file_name=str(data.get("source_file_name", "")),
            source_file_sha256=str(data.get("source_file_sha256", "")),
            updated_by=str(data.get("updated_by", "")),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
        )

    def to_dict(self) -> dict:
        """Serialize to a plain dict (for FileStorage JSON or API responses)."""
        d = {
            "client_id": self.client_id,
            "version": self.version,
            "ga4_property_id": self.ga4_property_id,
            "ga4_property_name": self.ga4_property_name,
            "ga4_client_name": self.ga4_client_name,
            "default_country": self.default_country,
            "expected_domain": self.expected_domain,
            "sources": self.sources,
            "mediums": self.mediums,
            "campaign_types": self.campaign_types,
            "campaign_notes": self.campaign_notes,
            "campaign_examples": self.campaign_examples,
            "medium_source_map": self.medium_source_map,
            "shared_link": self.shared_link,
            "shared_base_url": self.shared_base_url,
            "source_file_name": self.source_file_name,
            "source_file_sha256": self.source_file_sha256,
            "updated_by": self.updated_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        return d

    def validate(self) -> list[str]:
        """Return list of warning strings (non-fatal issues)."""
        warnings = []
        if not self.sources and not self.mediums:
            warnings.append("Nessun source o medium definito — il builder mostrerà solo input manuale")
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
# FirestoreStorage implementations
# ---------------------------------------------------------------------------

_firestore_client = None


def _get_firestore():
    """Lazy-init Firestore client (reused across calls)."""
    global _firestore_client
    if _firestore_client is None:
        from google.cloud import firestore
        _firestore_client = firestore.Client()
        logger.info("Firestore client initialized (project: %s)", _firestore_client.project)
    return _firestore_client


class FirestoreUTMHistoryStore:
    """UTM history backed by Firestore collection 'utm_history'."""

    def load_all(self) -> list[dict]:
        db = _get_firestore()
        docs = db.collection("utm_history").order_by("created_at", direction="DESCENDING").stream()
        return [doc.to_dict() for doc in docs]

    def load_for_user(self, user_email: str) -> list[dict]:
        eh = _email_hash(user_email)
        db = _get_firestore()
        docs = (
            db.collection("utm_history")
            .where("user_email_hash", "==", eh)
            .order_by("created_at", direction="DESCENDING")
            .stream()
        )
        return [doc.to_dict() for doc in docs]

    def upsert(self, entry: dict) -> None:
        eh = _email_hash(entry.get("user_email", ""))
        entry["user_email_hash"] = eh
        db = _get_firestore()
        # Composite key: user_email_hash + property_id + final_url
        doc_id = _email_hash(f"{eh}|{entry.get('property_id', '')}|{entry.get('final_url', '')}")
        db.collection("utm_history").document(doc_id).set(entry, merge=True)

    def write_all(self, items: list[dict]) -> None:
        db = _get_firestore()
        batch = db.batch()
        # Delete all existing
        for doc in db.collection("utm_history").stream():
            batch.delete(doc.reference)
        batch.commit()
        # Write new
        batch = db.batch()
        for entry in items:
            if not isinstance(entry, dict):
                continue
            eh = _email_hash(entry.get("user_email", ""))
            entry["user_email_hash"] = eh
            doc_id = _email_hash(f"{eh}|{entry.get('property_id', '')}|{entry.get('final_url', '')}")
            batch.set(db.collection("utm_history").document(doc_id), entry)
        batch.commit()

    def delete_for_user(self, user_email: str, final_url: str) -> None:
        eh = _email_hash(user_email)
        db = _get_firestore()
        docs = (
            db.collection("utm_history")
            .where("user_email_hash", "==", eh)
            .where("final_url", "==", final_url)
            .stream()
        )
        for doc in docs:
            doc.reference.delete()


class FirestoreClientConfigStore:
    """Client configs backed by Firestore collection 'client_configs'."""

    def load(self, client_id: str) -> Optional[dict]:
        from utm_normalize import normalize_client_id
        cid = normalize_client_id(client_id)
        if not cid:
            return None
        db = _get_firestore()
        doc = db.collection("client_configs").document(cid).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        # Validate schema
        try:
            _cfg, warnings = validate_client_config(data)
            for w in warnings:
                logger.warning("Client config '%s': %s", cid, w)
        except ClientConfigError as e:
            logger.error("Client config '%s' validation failed: %s", cid, e)
        return data

    def save(self, client_id: str, payload: dict) -> None:
        from utm_normalize import normalize_client_id
        cid = normalize_client_id(client_id)
        if not cid:
            raise ValueError("client_id non valido")
        body = dict(payload or {})
        body["client_id"] = cid
        validate_client_config(body)
        db = _get_firestore()
        db.collection("client_configs").document(cid).set(body)

    def list_ids(self) -> list[str]:
        db = _get_firestore()
        docs = db.collection("client_configs").stream()
        return sorted([doc.id for doc in docs])

    def delete(self, client_id: str) -> None:
        from utm_normalize import normalize_client_id
        cid = normalize_client_id(client_id)
        if not cid:
            return
        db = _get_firestore()
        db.collection("client_configs").document(cid).delete()


class FirestoreCredentialStore:
    """OAuth tokens and API keys backed by Firestore collection 'users'."""

    def save_token(self, user_email: str, creds_json: str) -> None:
        eh = _email_hash(user_email)
        db = _get_firestore()
        db.collection("users").document(eh).set(
            {"token_json": creds_json}, merge=True
        )

    def load_token(self, user_email: str) -> Optional[str]:
        eh = _email_hash(user_email)
        db = _get_firestore()
        doc = db.collection("users").document(eh).get()
        if not doc.exists:
            return None
        return doc.to_dict().get("token_json")

    def delete_token(self, user_email: str) -> None:
        eh = _email_hash(user_email)
        db = _get_firestore()
        doc_ref = db.collection("users").document(eh)
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            data.pop("token_json", None)
            if data:
                doc_ref.set(data)
            else:
                doc_ref.delete()

    def save_api_key(self, user_email: str, service: str, key: str) -> None:
        eh = _email_hash(user_email)
        db = _get_firestore()
        db.collection("users").document(eh).set(
            {f"api_key_{service}": key}, merge=True
        )

    def load_api_key(self, user_email: str, service: str) -> Optional[str]:
        eh = _email_hash(user_email)
        db = _get_firestore()
        doc = db.collection("users").document(eh).get()
        if not doc.exists:
            return None
        return doc.to_dict().get(f"api_key_{service}")



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


def create_firestore_stores() -> tuple[
    FirestoreUTMHistoryStore, FirestoreClientConfigStore, FirestoreCredentialStore
]:
    """Create all Firestore-backed stores."""
    return (
        FirestoreUTMHistoryStore(),
        FirestoreClientConfigStore(),
        FirestoreCredentialStore(),
    )


def create_stores(base_dir: Path):
    """Auto-select storage backend based on USE_FIRESTORE env var.

    If USE_FIRESTORE=1, uses Firestore. Otherwise, uses local JSON files.
    """
    import os
    if os.environ.get("USE_FIRESTORE", "").strip() in ("1", "true", "yes"):
        logger.info("Using Firestore storage backend")
        return create_firestore_stores()
    logger.info("Using file-based storage backend")
    return create_file_stores(base_dir)
