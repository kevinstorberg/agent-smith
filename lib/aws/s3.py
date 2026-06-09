import asyncio

from assets.errors import InvalidStorageKey
from lib.aws.base import AWSClientProtocol


def _validate_s3_key(key: str) -> str:
    if not key or key.startswith("/"):
        raise InvalidStorageKey(f"Invalid storage key: {key!r}")
    if ".." in key.split("/"):
        raise InvalidStorageKey(f"Invalid storage key: {key!r}")
    return key


def _is_not_found_error(error: Exception) -> bool:
    response = getattr(error, "response", {})
    code = str(response.get("Error", {}).get("Code", ""))
    return code in {"404", "NoSuchKey", "NotFound"}


class S3Client(AWSClientProtocol):
    def __init__(
        self,
        bucket: str = "",
        region: str = "us-east-1",
        *,
        client=None,
        aws_access_key_id: str = "",
        aws_secret_access_key: str = "",
    ) -> None:
        if not bucket:
            raise ValueError("bucket is required when using S3Client")
        self._bucket = bucket
        self._region = region
        self._client = client or self._create_client(
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
        )

    def _create_client(self, *, aws_access_key_id: str, aws_secret_access_key: str):
        try:
            import boto3
        except ImportError as e:
            raise RuntimeError("S3Client requires `poetry install --with aws`") from e

        kwargs = {"region_name": self._region}
        if aws_access_key_id:
            kwargs["aws_access_key_id"] = aws_access_key_id
        if aws_secret_access_key:
            kwargs["aws_secret_access_key"] = aws_secret_access_key
        return boto3.client("s3", **kwargs)

    def upload(self, key: str, content: bytes, content_type: str = "") -> str:
        key = _validate_s3_key(key)
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=content,
            ContentType=content_type or "application/octet-stream",
        )
        return key

    def download(self, key: str) -> bytes:
        key = _validate_s3_key(key)
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except Exception as e:
            if _is_not_found_error(e):
                raise FileNotFoundError(f"S3 object not found: {key}") from e
            raise
        return response["Body"].read()

    def delete(self, key: str) -> None:
        key = _validate_s3_key(key)
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def exists(self, key: str) -> bool:
        key = _validate_s3_key(key)
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except Exception as e:
            if _is_not_found_error(e):
                return False
            raise
        return True

    async def health_check(self) -> bool:
        try:
            await asyncio.to_thread(self._client.head_bucket, Bucket=self._bucket)
        except Exception:
            return False
        return True

    async def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            close()
        self._client = None
