from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

from config.models import FrontendConfig
from lib.agent_smith_core.paths import get_repo_root


class SPAStaticFiles(StaticFiles):
    def __init__(self, *, spa_fallback: bool, **kwargs) -> None:
        super().__init__(**kwargs)
        self.spa_fallback = spa_fallback

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code == 404 and self.spa_fallback:
                return await super().get_response("index.html", scope)
            raise


def mount_frontend(app: FastAPI, config: FrontendConfig, *, repo_root: Path | None = None) -> bool:
    if not config.enabled:
        return False

    mount_path = _normalize_mount_path(config.mount_path)
    static_dir = _resolve_static_dir(config.static_dir, repo_root=repo_root)
    index_path = static_dir / "index.html"
    if not index_path.is_file():
        raise RuntimeError(f"Frontend static assets are enabled but {index_path} does not exist")

    app.mount(
        mount_path,
        SPAStaticFiles(directory=static_dir, html=True, spa_fallback=config.spa_fallback),
        name="frontend",
    )
    return True


def _resolve_static_dir(static_dir: str, *, repo_root: Path | None = None) -> Path:
    path = Path(static_dir)
    if path.is_absolute():
        return path
    return (repo_root or get_repo_root(__file__)) / path


def _normalize_mount_path(mount_path: str) -> str:
    if not mount_path.startswith("/"):
        raise ValueError(f"Frontend mount_path must start with '/': {mount_path!r}")
    if mount_path != "/" and mount_path.endswith("/"):
        return mount_path.rstrip("/")
    return mount_path
