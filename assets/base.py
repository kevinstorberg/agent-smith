"""Storage backend protocol for template users.

TEMPLATE INFRASTRUCTURE: This module provides file storage abstraction.
It's intentionally unused by the template itself but ready for you to use
when your application needs to store files (user uploads, generated assets, etc.).

The storage backend follows the same pattern as memory and cache backends:
- Configure in config/default.yaml (storage.backend: "local" or "s3")
- Multiple implementations: LocalStorage (filesystem), S3Storage (AWS S3)
- Access via: from assets.backends import get_storage_backend

Example usage:
    from assets.backends import get_storage_backend

    storage = get_storage_backend()
    await storage.upload("user-123/avatar.jpg", image_bytes, "image/jpeg")
    exists = await storage.exists("user-123/avatar.jpg")
    data = await storage.download("user-123/avatar.jpg")
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageBackend(Protocol):
    """Protocol defining the interface all storage backends must implement.

    Template infrastructure: Provides consistent API across different storage
    implementations (local filesystem, S3, etc.).
    """

    async def upload(self, key: str, content: bytes, content_type: str = "") -> str:
        """Upload content to storage.

        Args:
            key: Storage key/path (e.g., "users/123/avatar.jpg")
            content: Binary content to store
            content_type: MIME type (e.g., "image/jpeg")

        Returns:
            Storage key where the content was saved
        """
        ...

    async def download(self, key: str) -> bytes:
        """Download content from storage.

        Args:
            key: Storage key/path to retrieve

        Returns:
            Binary content

        Raises:
            FileNotFoundError: If key doesn't exist
        """
        ...

    async def delete(self, key: str) -> None:
        """Delete content from storage.

        Args:
            key: Storage key/path to delete
        """
        ...

    async def exists(self, key: str) -> bool:
        """Check if content exists in storage.

        Args:
            key: Storage key/path to check

        Returns:
            True if key exists, False otherwise
        """
        ...
