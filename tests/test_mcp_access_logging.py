import logging

import pytest
from uvicorn.logging import AccessFormatter

from services.api.access_logging import ExpectedMCPProbeFilter, configure_mcp_access_logging
from services.api.app import MCP_SERVERS

ACCESS_MESSAGE = '%s - "%s %s HTTP/%s" %d'
PROBE_PATH = "/.well-known/oauth-protected-resource/mcp/memory"
DISCOVERY_PATHS = [
    prefix + document + suffix
    for document in ("oauth-protected-resource", "oauth-authorization-server", "openid-configuration")
    for prefix, suffix in (("/.well-known/", ""), ("/.well-known/", "/mcp/memory"), ("/mcp/memory/.well-known/", ""))
]


@pytest.fixture
def access_logger(caplog, monkeypatch):
    logger = logging.getLogger("uvicorn.access")
    debug_logger = logging.getLogger("uvicorn.access.expected_probe")
    monkeypatch.setattr(logger, "filters", [])
    monkeypatch.setattr(logger, "handlers", [caplog.handler])
    monkeypatch.setattr(logger, "propagate", False)
    monkeypatch.setattr(logger, "disabled", False)
    monkeypatch.setattr(debug_logger, "filters", [])
    monkeypatch.setattr(debug_logger, "handlers", [])
    monkeypatch.setattr(debug_logger, "propagate", True)
    monkeypatch.setattr(debug_logger, "disabled", False)
    caplog.set_level(logging.INFO, logger="uvicorn.access")
    caplog.set_level(logging.NOTSET, logger="uvicorn.access.expected_probe")
    configure_mcp_access_logging({"/mcp/memory": False})
    return logger


def emit(logger, path=PROBE_PATH, *, method="GET", status=404, level=logging.INFO):
    logger.log(level, ACCESS_MESSAGE, "127.0.0.1:1234", method, path, "1.1", status)


@pytest.mark.parametrize("path", DISCOVERY_PATHS)
def test_expected_discovery_is_quiet_at_info(access_logger, caplog, path):
    emit(access_logger, path)
    assert not caplog.records


@pytest.mark.parametrize("path", DISCOVERY_PATHS)
def test_expected_discovery_is_retained_at_debug_with_original_access_fields(access_logger, caplog, path):
    caplog.set_level(logging.DEBUG, logger="uvicorn.access")
    emit(access_logger, path)
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.name == "uvicorn.access.expected_probe" and record.levelno == logging.DEBUG
    assert record.expected_probe is True
    assert record.args == ("127.0.0.1:1234", "GET", path, "1.1", 404)
    assert "[expected_probe]" in record.getMessage()
    formatted = AccessFormatter('%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False).format(record)
    assert f"GET {path} HTTP/1.1" in formatted and "404 Not Found" in formatted and "DEBUG:" in formatted


@pytest.mark.parametrize("path,method,status,level", [
    (PROBE_PATH, "POST", 404, logging.INFO),
    (PROBE_PATH, "GET", 200, logging.INFO),
    (PROBE_PATH, "GET", 401, logging.INFO),
    (PROBE_PATH, "GET", 403, logging.INFO),
    (PROBE_PATH, "GET", 406, logging.INFO),
    (PROBE_PATH, "GET", 500, logging.INFO),
    (PROBE_PATH, "GET", 404, logging.WARNING),
    (PROBE_PATH, "GET", 404, logging.ERROR),
    (PROBE_PATH + "?unexpected=value", "GET", 404, logging.INFO),
    ("/.well-known/security.txt", "GET", 404, logging.INFO),
    ("/.well-known/oauth-protected-resource/mcp/unknown", "GET", 404, logging.INFO),
    ("/mcp/unknown/.well-known/oauth-protected-resource", "GET", 404, logging.INFO),
    ("/mcp/memory/", "GET", 406, logging.INFO),
    ("/api/profiles/not-found", "GET", 404, logging.INFO),
    ("/profiles/not-found", "GET", 404, logging.INFO),
])
def test_unexpected_requests_and_failures_keep_their_original_visibility(access_logger, caplog, path, method, status, level):
    emit(access_logger, path, method=method, status=status, level=level)
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.name == "uvicorn.access" and record.levelno == level
    assert record.args == ("127.0.0.1:1234", method, path, "1.1", status)
    assert not hasattr(record, "expected_probe")


@pytest.mark.parametrize("path", [
    "/.well-known/oauth-protected-resource", "/.well-known/oauth-authorization-server", "/.well-known/openid-configuration",
    "/.well-known/oauth-protected-resource/mcp/jobs", "/mcp/jobs/.well-known/oauth-protected-resource",
    "/.well-known/oauth-authorization-server/mcp/jobs", "/mcp/jobs/.well-known/openid-configuration",
])
def test_auth_enabled_mount_keeps_discovery_failures_visible(access_logger, caplog, path):
    configure_mcp_access_logging({"/mcp/memory": False, "/mcp/jobs": True})
    emit(access_logger, path)
    assert len(caplog.records) == 1 and caplog.records[0].name == "uvicorn.access"


def test_unauthenticated_mount_probe_stays_debug_when_another_mount_uses_auth(access_logger, caplog):
    configure_mcp_access_logging({"/mcp/memory": False, "/mcp/jobs": True})
    caplog.set_level(logging.DEBUG, logger="uvicorn.access")
    emit(access_logger)
    assert len(caplog.records) == 1 and caplog.records[0].name == "uvicorn.access.expected_probe"


def test_no_registered_mounts_does_not_hide_root_discovery(access_logger, caplog):
    configure_mcp_access_logging({})
    emit(access_logger, "/.well-known/oauth-protected-resource")
    assert len(caplog.records) == 1 and caplog.records[0].name == "uvicorn.access"


def test_configuration_is_idempotent_and_preserves_other_filters(access_logger):
    unrelated = logging.Filter()
    access_logger.addFilter(unrelated)
    configure_mcp_access_logging({"/mcp/memory": False})
    configure_mcp_access_logging({"/mcp/jobs": True})
    assert unrelated in access_logger.filters
    installed = [item for item in access_logger.filters if isinstance(item, ExpectedMCPProbeFilter)]
    assert len(installed) == 1 and not installed[0].paths


@pytest.mark.parametrize("args", [(), ("GET", PROBE_PATH, 404), {"path": PROBE_PATH}, ("client", "GET", [], "1.1", 404)])
def test_unknown_access_record_shapes_are_not_filtered(args):
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, "Unrecognized access message", (), None)
    record.args = args
    assert ExpectedMCPProbeFilter({"/mcp/memory": False}).filter(record)


def test_app_configures_filters_from_its_registered_mcp_mounts():
    installed = [item for item in logging.getLogger("uvicorn.access").filters if isinstance(item, ExpectedMCPProbeFilter)]
    assert len(installed) == 1
    for server in MCP_SERVERS:
        path = f"/.well-known/oauth-protected-resource/mcp/{server.name.split(' - ')[0]}"
        assert (path in installed[0].paths) is (server.settings.auth is None)
