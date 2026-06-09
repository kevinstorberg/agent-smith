import structlog

from src.utils.logging import configure_logging, get_logger


def test_configure_logging_uses_console_renderer_by_default():
    configure_logging()

    processors = structlog.get_config()["processors"]

    assert isinstance(processors[-1], structlog.dev.ConsoleRenderer)


def test_configure_logging_uses_json_renderer_when_requested():
    configure_logging(json_output=True)

    processors = structlog.get_config()["processors"]

    assert isinstance(processors[-1], structlog.processors.JSONRenderer)


def test_get_logger_returns_named_structlog_logger():
    configure_logging()

    logger = get_logger("agent_smith-test")

    assert logger is not None
