from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version

from fastapi import APIRouter

from src.settings import get_settings

router = APIRouter()

try:
    _VERSION = pkg_version("cairn")
except PackageNotFoundError:
    _VERSION = "0.1.0"


@router.get("/health")
async def health():
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": _VERSION,
    }
