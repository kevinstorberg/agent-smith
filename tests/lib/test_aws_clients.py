import pytest

from assets.errors import InvalidStorageKey
from lib.aws.documentdb import DocumentDBClient
from lib.aws.s3 import S3Client


@pytest.mark.asyncio
async def test_documentdb_health_pings_injected_client_and_close_closes_driver():
    backend = FakeDocumentDBClient()
    client = DocumentDBClient(client=backend)

    assert await client.health_check() is True

    await client.close()
    assert backend.closed is True
    assert await client.health_check() is False
    await client.close()


def test_documentdb_requires_connection_string_or_injected_client():
    with pytest.raises(ValueError, match="connection_string or injected client"):
        DocumentDBClient()


@pytest.mark.asyncio
async def test_documentdb_health_returns_false_when_ping_fails():
    client = DocumentDBClient(client=FakeDocumentDBClient(healthy=False))

    assert await client.health_check() is False


def test_s3_client_upload_download_delete_exists_roundtrip():
    backend = FakeS3Client()
    client = S3Client(bucket="bucket", client=backend)

    key = client.upload("file.txt", b"content", "text/plain")

    assert key == "file.txt"
    assert client.exists("file.txt") is True
    assert client.download("file.txt") == b"content"
    client.delete("file.txt")
    assert client.exists("file.txt") is False


def test_s3_client_rejects_path_traversal():
    client = S3Client(bucket="bucket", client=FakeS3Client())

    with pytest.raises(InvalidStorageKey, match="Invalid storage key"):
        client.upload("../secret.txt", b"content")


@pytest.mark.asyncio
async def test_s3_client_health_check_uses_bucket_access():
    backend = FakeS3Client()
    client = S3Client(bucket="bucket", client=backend)

    assert await client.health_check() is True

    backend.buckets.clear()
    assert await client.health_check() is False


class FakeS3NotFound(Exception):
    response = {"Error": {"Code": "NoSuchKey"}}


class FakeBody:
    def __init__(self, content: bytes) -> None:
        self._content = content

    def read(self) -> bytes:
        return self._content


class FakeS3Client:
    def __init__(self) -> None:
        self.buckets = {"bucket"}
        self.objects: dict[tuple[str, str], tuple[bytes, str]] = {}

    def head_bucket(self, *, Bucket):
        if Bucket not in self.buckets:
            raise FakeS3NotFound()
        return {}

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


class FakeDocumentDBAdmin:
    def __init__(self, owner: "FakeDocumentDBClient") -> None:
        self._owner = owner

    def command(self, command: str):
        if command != "ping":
            raise ValueError(f"unsupported command: {command}")
        if not self._owner.healthy or self._owner.closed:
            raise RuntimeError("DocumentDB ping failed")
        return {"ok": 1}


class FakeDocumentDBClient:
    def __init__(self, *, healthy: bool = True) -> None:
        self.healthy = healthy
        self.closed = False
        self.admin = FakeDocumentDBAdmin(self)

    def close(self) -> None:
        self.closed = True
