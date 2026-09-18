"""Raw snapshot storage: R2 in production, a local directory for development and tests.

Keys follow ``raw/{source_id}/{as_of}/{filename}``. A ``.meta.json`` sidecar next to each
object records where it came from, its size and its checksum.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, Protocol

from pipeline.http import HashingReader, copy_stream
from pipeline.settings import ROOT, r2_bucket_name, require_env

log = logging.getLogger(__name__)

LOCAL_RAW_DIR = ROOT / "data" / "raw"


def raw_key(source_id: str, as_of: str, filename: str) -> str:
    if "/" in source_id or "/" in filename:
        raise ValueError("source_id and filename must not contain '/'")
    return f"raw/{source_id}/{as_of}/{filename}"


class RawStore(Protocol):
    def exists(self, key: str) -> bool: ...
    def put(self, key: str, reader: HashingReader, content_type: str | None = None) -> None: ...
    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None: ...
    def get_bytes(self, key: str) -> bytes: ...
    def open(self, key: str) -> IO[bytes]: ...
    def list(self, prefix: str) -> list[str]: ...


class LocalStore:
    """Files under a directory. Used when COMEBACKTOWNS_RAW_STORE=local and in tests."""

    def __init__(self, root: Path = LOCAL_RAW_DIR) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError(f"key escapes store root: {key}")
        return path

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def put(self, key: str, reader: HashingReader, content_type: str | None = None) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        with tmp.open("wb") as out:
            copy_stream(reader, out)
        tmp.replace(path)

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def open(self, key: str) -> IO[bytes]:
        return self._path(key).open("rb")

    def list(self, prefix: str) -> list[str]:
        base = self._path(prefix) if prefix else self.root
        if base.is_file():
            return [prefix]
        if not base.is_dir():
            return []
        return sorted(str(p.relative_to(self.root)) for p in base.rglob("*") if p.is_file())


class R2Store:
    """Cloudflare R2 through its S3-compatible API (boto3)."""

    def __init__(self, bucket: str, client: Any) -> None:
        self.bucket = bucket
        self.client = client

    @classmethod
    def from_env(cls, bucket: str | None = None) -> R2Store:
        import boto3

        account_id = require_env("CLOUDFLARE_ACCOUNT_ID")
        access_key = os.environ.get("R2_ACCESS_KEY_ID")
        secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
        if not (access_key and secret_key):
            access_key, secret_key = derive_r2_credentials()
        client = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",
        )
        return cls(bucket or r2_bucket_name(), client)

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise
        return True

    def put(self, key: str, reader: HashingReader, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        self.client.upload_fileobj(reader, self.bucket, key, ExtraArgs=extra or None)

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None:
        kwargs: dict[str, Any] = {"Bucket": self.bucket, "Key": key, "Body": data}
        if content_type:
            kwargs["ContentType"] = content_type
        self.client.put_object(**kwargs)

    def get_bytes(self, key: str) -> bytes:
        body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        return bytes(body.read())

    def open(self, key: str) -> IO[bytes]:
        body: IO[bytes] = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        return body

    def list(self, prefix: str) -> list[str]:
        keys: list[str] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys.extend(obj["Key"] for obj in page.get("Contents", []))
        return keys


def derive_r2_credentials() -> tuple[str, str]:
    """S3 credentials from the Cloudflare API token.

    Per Cloudflare's R2 docs the S3 access key id is the API token's id and the secret is the
    SHA-256 hex digest of the token value, so no second secret is needed. The token must
    carry the Workers R2 Storage:Edit permission.
    """
    import httpx

    token = require_env("CLOUDFLARE_API_TOKEN")
    response = httpx.get(
        "https://api.cloudflare.com/client/v4/user/tokens/verify",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        raise RuntimeError("CLOUDFLARE_API_TOKEN could not be verified")
    token_id = str(payload["result"]["id"])
    return token_id, hashlib.sha256(token.encode()).hexdigest()


def raw_store() -> RawStore:
    """The configured store: local when COMEBACKTOWNS_RAW_STORE=local, else R2."""
    if os.environ.get("COMEBACKTOWNS_RAW_STORE", "r2").lower() == "local":
        log.info("raw store: local directory %s", LOCAL_RAW_DIR)
        return LocalStore()
    return R2Store.from_env()


def write_meta(
    store: RawStore, key: str, *, url: str, size: int, sha256: str, content_type: str | None
) -> None:
    meta = {
        "key": key,
        "url": url,
        "bytes": size,
        "sha256": sha256,
        "content_type": content_type,
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    store.put_bytes(key + ".meta.json", json.dumps(meta, indent=2).encode(), "application/json")


def read_meta(store: RawStore, key: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(store.get_bytes(key + ".meta.json"))
    return data
