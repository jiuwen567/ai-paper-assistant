import boto3
from botocore.config import Config
from django.conf import settings


def s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        region_name=settings.S3_REGION,
        config=Config(
            connect_timeout=3,
            read_timeout=3,
            retries={"max_attempts": 0},
            s3={"addressing_style": "path"},
        ),
    )
