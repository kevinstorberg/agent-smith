from __future__ import annotations

import logging
from collections.abc import Mapping

_DISCOVERY_DOCUMENTS = ("oauth-protected-resource", "oauth-authorization-server", "openid-configuration")


class ExpectedMCPDiscoveryFilter(logging.Filter):
    def __init__(self, authenticated_mounts: Mapping[str, bool]) -> None:
        super().__init__()
        self.paths = {
            path
            for mount, authenticated in authenticated_mounts.items() if not authenticated
            for document in _DISCOVERY_DOCUMENTS
            for path in (f"{mount}/.well-known/{document}", f"/.well-known/{document}{mount}")
        }
        if authenticated_mounts and not any(authenticated_mounts.values()):
            self.paths.update(f"/.well-known/{document}" for document in _DISCOVERY_DOCUMENTS)
        self.debug_logger = logging.getLogger("uvicorn.access.expected_probe")

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "uvicorn.access" or record.levelno != logging.INFO or not isinstance(record.args, tuple) or len(record.args) != 5:
            return True
        _, method, path, _, status = record.args
        if method != "GET" or not isinstance(path, str) or type(status) is not int or status != 404 or path not in self.paths:
            return True
        # Preserve Uvicorn's five access fields for its formatter and structured handlers.
        self.debug_logger.debug("[expected_probe] " + str(record.msg), *record.args, extra={"expected_probe": True})
        return False


def configure_mcp_access_logging(authenticated_mounts: Mapping[str, bool]) -> None:
    logger = logging.getLogger("uvicorn.access")
    for current in tuple(logger.filters):
        if isinstance(current, ExpectedMCPDiscoveryFilter):
            logger.removeFilter(current)
    logger.addFilter(ExpectedMCPDiscoveryFilter(authenticated_mounts))
