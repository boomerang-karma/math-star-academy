"""Identity-based grants for resources owned by another stack.

CDK's ``secret.grant_read()`` adds the reader's role ARN to the KMS *key policy*
when the key lives in another stack, which creates a stack dependency cycle
(the key's stack would need the reader's stack). The keys' default policy
delegates to IAM, so identity policies on the reader are sufficient; these
helpers write exactly those statements.
"""

from __future__ import annotations

from aws_cdk import Stack
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_secretsmanager as secretsmanager


def allow_secret_read(
    grantee: iam.IGrantable, *secrets: secretsmanager.ISecret, key: kms.IKey
) -> None:
    principal = grantee.grant_principal
    principal.add_to_principal_policy(
        iam.PolicyStatement(
            actions=["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
            resources=[secret.secret_arn for secret in secrets],
        )
    )
    principal.add_to_principal_policy(
        iam.PolicyStatement(
            actions=["kms:Decrypt"],
            resources=[key.key_arn],
            conditions={
                "StringEquals": {
                    "kms:ViaService": f"secretsmanager.{Stack.of(key).region}.amazonaws.com"
                }
            },
        )
    )
