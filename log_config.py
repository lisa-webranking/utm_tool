"""
Centralized logging configuration.

On Cloud Run: JSON format compatible with Cloud Logging (severity, message, module).
Locally: human-readable format with timestamp and level.

Call setup_logging() once at app startup (app.py top-level).
"""
import json
import logging
import os
import sys


class CloudJsonFormatter(logging.Formatter):
    """JSON formatter that Cloud Logging parses automatically.

    Maps Python log levels to Cloud Logging severity:
    https://cloud.google.com/logging/docs/reference/v2/rest/v2/LogEntry#LogSeverity
    """

    _SEVERITY = {
        logging.DEBUG: "DEBUG",
        logging.INFO: "INFO",
        logging.WARNING: "WARNING",
        logging.ERROR: "ERROR",
        logging.CRITICAL: "CRITICAL",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "severity": self._SEVERITY.get(record.levelno, "DEFAULT"),
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
        }
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception"] = self.formatException(record.exc_info)
        # Merge extra fields added via logger.info("msg", extra={...})
        for key in ("user_email", "client_id", "property_id", "action"):
            val = getattr(record, key, None)
            if val is not None:
                payload[key] = val
        return json.dumps(payload, ensure_ascii=False)


class LocalFormatter(logging.Formatter):
    """Compact readable format for local development."""

    def __init__(self):
        super().__init__(
            fmt="%(asctime)s %(levelname)-8s [%(module)s] %(message)s",
            datefmt="%H:%M:%S",
        )


def setup_logging() -> None:
    """Configure root logger. Call once at startup."""
    is_cloud = bool(os.environ.get("K_SERVICE"))  # Cloud Run sets K_SERVICE

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(CloudJsonFormatter() if is_cloud else LocalFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    # Reduce noise from third-party libs
    for noisy in ("google", "urllib3", "grpc", "httplib2"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
