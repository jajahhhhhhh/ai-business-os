"""MinIO (S3-compatible) object storage adapter.

boto3 is synchronous, so every call is wrapped in asyncio.to_thread; boto3
clients are thread-safe. The bucket is created on first write so a fresh
MinIO container needs no manual setup.
"""

from __future__ import annotations

import asyncio
import threading

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError


class S3ObjectStorage:
    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str) -> None:
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",  # MinIO ignores it but boto3 requires one
        )
        self._bucket_ready = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------ sync core

    def _ensure_bucket(self) -> None:
        with self._lock:
            if self._bucket_ready:
                return
            try:
                self._client.head_bucket(Bucket=self._bucket)
            except ClientError:
                self._client.create_bucket(Bucket=self._bucket)
            self._bucket_ready = True

    def _put(self, key: str, data: bytes, content_type: str) -> None:
        self._ensure_bucket()
        self._client.put_object(
            Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
        )

    def _get(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        body: bytes = response["Body"].read()
        return body

    def _presign(self, key: str, expires_seconds: int) -> str:
        url: str = self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_seconds,
        )
        return url

    # ------------------------------------------------------------ async port

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(self._put, key, data, content_type)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._get, key)

    async def presign(self, key: str, expires_seconds: int = 3600) -> str:
        return await asyncio.to_thread(self._presign, key, expires_seconds)
