import pytest

from assets.backends.local import LocalStorage
from assets.base import StorageBackend


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(base_path=str(tmp_path))


@pytest.mark.integration
class TestLocalStorage:
    async def test_upload_and_download(self, storage):
        content = b"hello world"
        key = await storage.upload("test.txt", content, content_type="text/plain")
        retrieved = await storage.download(key)
        assert retrieved == content

    async def test_delete_removes_file(self, storage):
        key = await storage.upload("deleteme.txt", b"data", content_type="text/plain")
        await storage.delete(key)
        assert not await storage.exists(key)

    async def test_download_missing_raises(self, storage):
        with pytest.raises(FileNotFoundError):
            await storage.download("nonexistent.txt")

    async def test_exists_returns_true_for_existing(self, storage):
        key = await storage.upload("exists.txt", b"data", content_type="text/plain")
        assert await storage.exists(key) is True

    async def test_exists_returns_false_for_missing(self, storage):
        assert await storage.exists("missing.txt") is False

    async def test_implements_protocol(self, storage):
        assert isinstance(storage, StorageBackend)
