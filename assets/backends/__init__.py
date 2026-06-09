"""Storage backend factory for template users.

TEMPLATE INFRASTRUCTURE: Entry point for accessing file storage.
Configure which backend to use in config/default.yaml:
    storage:
      backend: local  # or "s3"
      local_path: ./storage

Example usage:
    from assets.backends import get_storage_backend

    storage = get_storage_backend()
    await storage.upload("files/document.pdf", pdf_bytes, "application/pdf")
"""

from assets.base import StorageBackend
from config.loader import load_default_config
from config.models import StorageConfig


def create_storage_backend(config: StorageConfig) -> StorageBackend:
    """Create a storage backend from explicit storage config."""
    backend_name = config.backend.lower()

    if backend_name == "local":
        from assets.backends.local import LocalStorage

        return LocalStorage(base_path=config.local_path)
    elif backend_name == "s3":
        from assets.backends.s3 import S3Storage

        return S3Storage()

    raise ValueError(f"Unknown storage backend: {backend_name!r}. " f"Valid options: local, s3")


def get_storage_backend() -> StorageBackend:
    """Get storage backend instance based on configuration."""
    config = load_default_config()
    return create_storage_backend(config.storage)
