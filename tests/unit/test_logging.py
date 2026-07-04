import json
import logging

from services.common.logging import JsonFormatter, bind_incident, configure


def _format(logger_name: str, msg: str, **kwargs) -> dict:
    record = logging.LogRecord(
        name=logger_name, level=logging.INFO, pathname="", lineno=0,
        msg=msg, args=(), exc_info=None,
    )
    for k, v in kwargs.items():
        setattr(record, k, v)
    return json.loads(JsonFormatter("quarantine").format(record))


def test_json_line_shape():
    doc = _format("t", "recant complete")
    assert doc["service"] == "quarantine"
    assert doc["level"] == "info"
    assert doc["msg"] == "recant complete"
    assert "ts" in doc


def test_incident_id_correlated_inside_bind():
    with bind_incident("inc-123"):
        doc = _format("t", "flipping closure")
    assert doc["incident_id"] == "inc-123"


def test_no_incident_id_outside_bind():
    doc = _format("t", "healthz")
    assert "incident_id" not in doc


def test_extra_fields_merged():
    doc = _format("t", "closure computed", fields={"belief_count": 3, "rounds": 2})
    assert doc["belief_count"] == 3
    assert doc["rounds"] == 2


def test_configure_idempotent():
    a = configure("svc-x")
    b = configure("svc-x")
    assert a is b
    assert len(a.handlers) == 1
