import json
import logging

from app.core.logs import JsonFormatter, RequestIdFilter, configure_logging, request_id_var


def make_record(message: str = "проверка") -> logging.LogRecord:
    return logging.LogRecord("test", logging.INFO, __file__, 1, message, None, None)


def test_filter_injects_current_request_id():
    token = request_id_var.set("abc123")
    try:
        record = make_record()
        assert RequestIdFilter().filter(record) is True
        assert record.request_id == "abc123"
    finally:
        request_id_var.reset(token)


def test_filter_falls_back_when_no_request():
    record = make_record()
    RequestIdFilter().filter(record)
    assert record.request_id == "-"


def test_json_formatter_emits_single_line_json():
    record = make_record("сообщение")
    record.request_id = "req-1"
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "сообщение"
    assert payload["level"] == "INFO"
    assert payload["request_id"] == "req-1"
    assert payload["logger"] == "test"


def test_json_formatter_includes_exception():
    try:
        raise RuntimeError("сломалось")
    except RuntimeError:
        import sys

        record = make_record()
        record.exc_info = sys.exc_info()
    payload = json.loads(JsonFormatter().format(record))
    assert "RuntimeError" in payload["exception"]


def test_configure_logging_replaces_handlers():
    root = logging.getLogger()
    previous_handlers = list(root.handlers)
    previous_level = root.level
    try:
        configure_logging("WARNING", json_output=True)
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JsonFormatter)
        assert root.level == logging.WARNING
        assert logging.getLogger("uvicorn.access").disabled is True
    finally:
        root.handlers[:] = previous_handlers
        root.setLevel(previous_level)
