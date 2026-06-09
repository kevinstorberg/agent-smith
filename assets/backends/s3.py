import asyncio

from assets.base import StorageBackend
from lib.aws.s3 import S3Client
from src.settings import get_settings


class S3Storage(StorageBackend):
    def __init__(self, *, bucket: str | None = None, client=None):
        settings = get_settings()
        bucket_name = bucket or settings.S3_BUCKET
        if not bucket_name:
            raise ValueError("S3_BUCKET is required when using S3Storage")
        if isinstance(client, S3Client):
            self._client = client
        else:
            self._client = S3Client(
                bucket=bucket_name,
                region=settings.AWS_REGION,
                client=client,
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            )

    async def upload(self, key: str, content: bytes, content_type: str = "") -> str:
        return await asyncio.to_thread(self._client.upload, key, content, content_type)

    async def download(self, key: str) -> bytes:
        return await asyncio.to_thread(self._client.download, key)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.delete, key)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._client.exists, key)
