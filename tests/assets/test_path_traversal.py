import pytest

from assets.backends.local import LocalStorage
from assets.errors import InvalidStorageKey


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(base_path=str(tmp_path))


@pytest.mark.unit
class TestPathTraversalPrevention:
    async def test_dotdot_in_key_rejected(self, storage):
        with pytest.raises(InvalidStorageKey, match="Invalid storage key"):
            await storage.upload("../escape.txt", b"data", "text/plain")

    async def test_absolute_path_rejected(self, storage):
        with pytest.raises(InvalidStorageKey, match="Invalid storage key"):
            await storage.upload("/etc/passwd", b"data", "text/plain")

    async def test_empty_key_rejected(self, storage):
        with pytest.raises(InvalidStorageKey, match="Invalid storage key"):
            await storage.upload("", b"data", "text/plain")

    async def test_nested_dotdot_rejected(self, storage):
        with pytest.raises(InvalidStorageKey, match="Invalid storage key"):
            await storage.upload("subdir/../../escape.txt", b"data", "text/plain")

    async def test_dotdot_in_download_rejected(self, storage):
        with pytest.raises(InvalidStorageKey, match="Invalid storage key"):
            await storage.download("../etc/passwd")

    async def test_dotdot_in_delete_rejected(self, storage):
        with pytest.raises(InvalidStorageKey, match="Invalid storage key"):
            await storage.delete("../important.txt")

    async def test_dotdot_in_exists_rejected(self, storage):
        with pytest.raises(InvalidStorageKey, match="Invalid storage key"):
            await storage.exists("../secret.txt")

    async def test_valid_nested_key_accepted(self, storage):
        key = await storage.upload("subdir/nested/file.txt", b"data", "text/plain")
        assert key == "subdir/nested/file.txt"
        assert await storage.exists("subdir/nested/file.txt")
