import sys
from types import SimpleNamespace

import pytest

import assets.backends as storage_backends
from assets.backends import create_storage_backend
from assets.backends.local import LocalStorage
from assets.backends.s3 import S3Storage
from config.models import DefaultConfig, StorageConfig


@pytest.fixture(autouse=True)
def reset_settings_cache():
    from src.settings import reset_settings

    reset_settings()
    yield
    reset_settings()


def test_create_storage_backend_returns_local_backend(tmp_path):
    backend = create_storage_backend(StorageConfig(backend="local", local_path=str(tmp_path)))

    assert isinstance(backend, LocalStorage)


def test_get_storage_backend_returns_local_backend(monkeypatch, tmp_path):
    config = DefaultConfig(storage=StorageConfig(backend="local", local_path=str(tmp_path)))
    monkeypatch.setattr(storage_backends, "load_default_config", lambda: config)

    backend = storage_backends.get_storage_backend()
    assert isinstance(backend, LocalStorage)


def test_get_storage_backend_returns_s3_backend(monkeypatch):
    config = DefaultConfig(storage=StorageConfig(backend="s3"))
    monkeypatch.setattr(storage_backends, "load_default_config", lambda: config)
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=lambda *args, **kwargs: FakeS3Client()))

    backend = storage_backends.get_storage_backend()

    assert isinstance(backend, S3Storage)


def test_create_storage_backend_rejects_unknown_backend():
    with pytest.raises(ValueError, match="Unknown storage backend"):
        create_storage_backend(StorageConfig(backend="unknown"))


def test_s3_storage_requires_bucket():
    with pytest.raises(ValueError, match="S3_BUCKET is required"):
        S3Storage(client=FakeS3Client())


@pytest.mark.asyncio
async def test_s3_storage_upload_download_delete_exists_roundtrip():
    client = FakeS3Client()
    backend = S3Storage(bucket="test-bucket", client=client)

    key = await backend.upload("file.txt", b"content", "text/plain")

    assert key == "file.txt"
    assert await backend.exists("file.txt") is True
    assert await backend.download("file.txt") == b"content"
    await backend.delete("file.txt")
    assert await backend.exists("file.txt") is False


@pytest.mark.asyncio
async def test_s3_storage_rejects_path_traversal():
    backend = S3Storage(bucket="test-bucket", client=FakeS3Client())

    with pytest.raises(ValueError, match="Invalid storage key"):
        await backend.upload("../secret.txt", b"content")


class FakeS3NotFound(Exception):
    response = {"Error": {"Code": "NoSuchKey"}}


class FakeBody:
    def __init__(self, content: bytes) -> None:
        self._content = content

    def read(self) -> bytes:
        return self._content


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, str]] = {}

    def put_object(self, *, Bucket, Key, Body, ContentType):
        self.objects[(Bucket, Key)] = (Body, ContentType)

    def get_object(self, *, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise FakeS3NotFound()
        content, _ = self.objects[(Bucket, Key)]
        return {"Body": FakeBody(content)}

    def head_object(self, *, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise FakeS3NotFound()
        return {}

    def delete_object(self, *, Bucket, Key):
        self.objects.pop((Bucket, Key), None)
