"""Structured JSON logging with incident_id correlation (spec section 9).

One JSON object per line on stdout. Anything logged inside a bind_incident()
block carries that incident_id, so a whole recant is greppable by incident.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

incident_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "incident_id", default=None
)


@contextmanager
def bind_incident(incident_id: str) -> Iterator[None]:
    token = incident_id_var.set(incident_id)
    try:
        yield
    finally:
        incident_id_var.reset(token)


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str):
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        doc: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "service": self._service,
            "msg": record.getMessage(),
        }
        incident_id = incident_id_var.get()
        if incident_id is not None:
            doc["incident_id"] = incident_id
        fields = getattr(record, "fields", None)
        if fields:
            doc.update(fields)
        if record.exc_info and record.exc_info[0] is not None:
            doc["exc"] = self.formatException(record.exc_info)
        return json.dumps(doc, default=str)


def configure(service: str) -> logging.Logger:
    """Idempotent per service name; returns the service logger."""
    logger = logging.getLogger(service)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter(service))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger
