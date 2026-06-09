from pathlib import Path

from assets.base import StorageBackend
from assets.errors import InvalidStorageKey


def _validate_key(base: Path, key: str) -> Path:
    """Validate storage key to prevent path traversal.

    Rejects keys containing '..', absolute paths, or any path
    that resolves outside the base directory.
    """
    if not key or key.startswith("/"):
        raise InvalidStorageKey(f"Invalid storage key: {key!r}")
    if ".." in key.split("/"):
        raise InvalidStorageKey(f"Invalid storage key: {key!r}")

    resolved = (base / key).resolve()
    if not resolved.is_relative_to(base):
        raise InvalidStorageKey(f"Storage key escapes base directory: {key!r}")

    return resolved


class LocalStorage(StorageBackend):
    def __init__(self, base_path: str):
        self._base = Path(base_path).resolve()
        self._base.mkdir(parents=True, exist_ok=True)

    async def upload(self, key: str, content: bytes, content_type: str = "") -> str:
        path = _validate_key(self._base, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return key

    async def download(self, key: str) -> bytes:
        path = _validate_key(self._base, key)
        if not path.exists():
            raise FileNotFoundError(f"Asset not found: {key}")
        return path.read_bytes()

    async def delete(self, key: str) -> None:
        path = _validate_key(self._base, key)
        if path.exists():
            path.unlink()

    async def exists(self, key: str) -> bool:
        path = _validate_key(self._base, key)
        return path.exists()
