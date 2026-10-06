"""An S3 bucket with the platform's non-negotiable defaults.

Public access blocked, TLS required, SSE-KMS (or SSE-S3 where AWS requires it),
versioning, server access logging, and an explicit removal policy. Buckets are
never auto-emptied by CloudFormation: ``scripts/aws/teardown.sh`` empties them
deliberately, so a stray ``cdk destroy`` cannot silently delete data.
"""

from __future__ import annotations

from collections.abc import Sequence

from aws_cdk import Duration, RemovalPolicy
from aws_cdk import aws_kms as kms
from aws_cdk import aws_s3 as s3
from constructs import Construct


def secure_bucket(
    scope: Construct,
    construct_id: str,
    *,
    encryption_key: kms.IKey | None,
    removal_policy: RemovalPolicy,
    access_logs: s3.IBucket | None = None,
    lifecycle_rules: Sequence[s3.LifecycleRule] = (),
    versioned: bool = True,
    object_lock_default_retention: s3.ObjectLockRetention | None = None,
    object_ownership: s3.ObjectOwnership = s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
) -> s3.Bucket:
    return s3.Bucket(
        scope,
        construct_id,
        block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        enforce_ssl=True,
        minimum_tls_version=1.2,
        encryption=s3.BucketEncryption.KMS if encryption_key else s3.BucketEncryption.S3_MANAGED,
        encryption_key=encryption_key,
        bucket_key_enabled=encryption_key is not None,
        versioned=versioned or object_lock_default_retention is not None,
        object_lock_enabled=object_lock_default_retention is not None or None,
        object_lock_default_retention=object_lock_default_retention,
        object_ownership=object_ownership,
        server_access_logs_bucket=access_logs,
        server_access_logs_prefix=f"{construct_id.lower()}/" if access_logs else None,
        lifecycle_rules=[
            s3.LifecycleRule(
                id="abort-incomplete-uploads",
                abort_incomplete_multipart_upload_after=Duration.days(1),
            ),
            *lifecycle_rules,
        ],
        removal_policy=removal_policy,
        auto_delete_objects=False,
    )
