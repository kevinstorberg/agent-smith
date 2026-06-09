"""Service registry with auto-import.

All service modules in this package are automatically imported on package load,
triggering @register_service decorators without manual imports.
"""

import importlib
import logging
import pkgutil

from lib.cairn.paths import get_module_dir

logger = logging.getLogger(__name__)


def _auto_import_services():
    """Auto-import all service modules to trigger @register_service decorators."""
    services_dir = get_module_dir(__file__)

    for _, module_name, _ in pkgutil.iter_modules([str(services_dir)]):
        if module_name.startswith("_") or module_name == "base":
            continue
        try:
            importlib.import_module(f"src.services.{module_name}")
            logger.debug(f"Auto-imported service module: {module_name}")
        except ImportError as e:
            logger.warning(f"Failed to import service module {module_name}: {e}")


_auto_import_services()
