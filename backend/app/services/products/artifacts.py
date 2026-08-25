"""Artifact storage — MinIO PRIMARY through the S3 API (generation ->
MinIO -> mirrored to S3 when connectivity exists, never the reverse;
the engine never thinks about the mirror). MinIO runs as a subprocess
inside this container on loopback; the backend fronts all serving."""
import logging
import os
from functools import lru_cache

log = logging.getLogger(__name__)

BUCKET = os.environ.get("PRODUCTS_BUCKET", "products")
ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://127.0.0.1:9000")


@lru_cache(maxsize=1)
def _client():
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3", endpoint_url=ENDPOINT,
        aws_access_key_id=os.environ.get("MINIO_ROOT_USER", "geoagent"),
        aws_secret_access_key=os.environ.get(
            "MINIO_ROOT_PASSWORD", "geoagent-artifacts"),
        config=Config(signature_version="s3v4",
                      retries={"max_attempts": 2}),
        region_name="us-east-1")


def _ensure_bucket(bucket: str = None):
    c = _client()
    bucket = bucket or BUCKET
    try:
        c.head_bucket(Bucket=bucket)
    except Exception:
        c.create_bucket(Bucket=bucket)


def put_bytes(object_key: str, data: bytes, content_type: str,
              bucket: str = None) -> str:
    _ensure_bucket(bucket)
    _client().put_object(Bucket=bucket or BUCKET, Key=object_key,
                         Body=data, ContentType=content_type)
    return object_key


def head_object(object_key: str, bucket: str = None):
    """Returns (size_bytes, last_modified_ms) without downloading —
    CheckFileInfo's Size/Version come from here (the IBL host used
    stat(); this is the object-store equivalent)."""
    r = _client().head_object(Bucket=bucket or BUCKET, Key=object_key)
    return (r["ContentLength"],
            int(r["LastModified"].timestamp() * 1000))


def get_object(object_key: str, bucket: str = None):
    """Returns (bytes, content_type). Raises on a missing key —
    a missing artifact is a visible error, never a silent blank."""
    r = _client().get_object(Bucket=bucket or BUCKET, Key=object_key)
    return r["Body"].read(), r.get("ContentType",
                                   "application/octet-stream")
