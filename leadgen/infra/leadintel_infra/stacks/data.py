"""Data plane: Aurora PostgreSQL (system of record) and the S3 zones (data lake).

Aurora Serverless v2 runs in the isolated subnets with storage encryption, IAM
auth, forced TLS, Performance Insights and exported logs. Applications never
hold a database password: Lambdas get IAM tokens for RDS Proxy, and the proxy
holds per-role login secrets (``leadintel_api`` -> app role,
``leadintel_worker`` -> pipeline role), created by the migrator Lambda.

S3 zones
  raw       bronze: verbatim upstream payloads, SSE-KMS, short retention
  curated   silver/gold exports for Athena/BI
  audit     Object Lock (WORM) anchors of the audit hash chain
  logs      server access logs (SSE-S3: S3 cannot log to SSE-KMS buckets)
"""

from __future__ import annotations

from typing import Any

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_athena as athena
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_glue as glue
from aws_cdk import aws_kms as kms
from aws_cdk import aws_rds as rds
from aws_cdk import aws_s3 as s3
from constructs import Construct

from leadintel_infra.config import EnvConfig
from leadintel_infra.constructs.python_function import retention
from leadintel_infra.constructs.secure_bucket import secure_bucket
from leadintel_infra.stacks.network import NetworkStack
from leadintel_infra.stacks.security import SecurityStack

API_DB_USER = "leadintel_api"
WORKER_DB_USER = "leadintel_worker"


class DataStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cfg: EnvConfig,
        network: NetworkStack,
        security: SecurityStack,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        removal = RemovalPolicy.RETAIN if cfg.is_production else RemovalPolicy.DESTROY
        key = security.data_key
        # Database storage, Performance Insights and DB credentials use a key owned by this
        # stack, so RDS Proxy and secret rotation grants never cross a stack boundary.
        self.db_key = kms.Key(
            self,
            "DatabaseKey",
            alias=f"alias/{cfg.prefix}/database",
            enable_key_rotation=True,
            description="LeadIntel Aurora storage and credentials",
            removal_policy=removal,
            pending_window=Duration.days(30 if cfg.is_production else 7),
        )

        self.db_sg = ec2.SecurityGroup(
            self,
            "DatabaseSg",
            vpc=network.vpc,
            description="Aurora and RDS Proxy",
            allow_all_outbound=False,
        )
        self.db_sg.add_ingress_rule(
            network.lambda_sg, ec2.Port.tcp(5432), "PostgreSQL from Lambdas"
        )
        self.db_sg.add_ingress_rule(self.db_sg, ec2.Port.tcp(5432), "RDS Proxy to Aurora")
        self.db_sg.add_egress_rule(self.db_sg, ec2.Port.tcp(5432), "RDS Proxy to Aurora")

        params = rds.ParameterGroup(
            self,
            "ClusterParams",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_16_9
            ),
            parameters={
                "rds.force_ssl": "1",
                "log_min_duration_statement": "1000",
                "log_connections": "1",
                "log_disconnections": "1",
                "idle_in_transaction_session_timeout": "60000",
            },
        )
        writer = rds.ClusterInstance.serverless_v2(
            "writer",
            enable_performance_insights=True,
            performance_insight_encryption_key=self.db_key,
        )
        readers = (
            [
                rds.ClusterInstance.serverless_v2(
                    "reader",
                    scale_with_writer=True,
                    enable_performance_insights=True,
                    performance_insight_encryption_key=self.db_key,
                )
            ]
            if cfg.db_reader
            else []
        )
        self.cluster = rds.DatabaseCluster(
            self,
            "Cluster",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_16_9
            ),
            writer=writer,
            readers=readers,
            serverless_v2_min_capacity=cfg.db_min_acu,
            serverless_v2_max_capacity=cfg.db_max_acu,
            vpc=network.vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
            security_groups=[self.db_sg],
            default_database_name="leadintel",
            credentials=rds.Credentials.from_generated_secret(
                "leadintel_admin", encryption_key=self.db_key, secret_name=f"{cfg.prefix}/db/admin"
            ),
            parameter_group=params,
            storage_encrypted=True,
            storage_encryption_key=self.db_key,
            iam_authentication=True,
            backup=rds.BackupProps(
                retention=Duration.days(cfg.db_backup_days), preferred_window="03:00-04:00"
            ),
            preferred_maintenance_window="sun:04:30-sun:05:30",
            cloudwatch_logs_exports=["postgresql"],
            cloudwatch_logs_retention=retention(cfg.log_retention_days),
            monitoring_interval=Duration.seconds(60),
            deletion_protection=cfg.deletion_protection,
            removal_policy=RemovalPolicy.SNAPSHOT
            if cfg.db_removal == "snapshot"
            else RemovalPolicy.DESTROY,
            copy_tags_to_snapshot=True,
        )
        assert self.cluster.secret is not None
        self.admin_secret = self.cluster.secret
        self.cluster.add_rotation_single_user(automatically_after=Duration.days(30))

        def login_secret(name: str, username: str) -> rds.DatabaseSecret:
            secret = rds.DatabaseSecret(
                self,
                name,
                username=username,
                encryption_key=self.db_key,
                secret_name=f"{cfg.prefix}/db/{username}",
            )
            return secret.attach(self.cluster)  # type: ignore[return-value]

        self.api_db_secret = login_secret("ApiDbUser", API_DB_USER)
        self.worker_db_secret = login_secret("WorkerDbUser", WORKER_DB_USER)

        self.proxy = self.cluster.add_proxy(
            "Proxy",
            secrets=[self.admin_secret, self.api_db_secret, self.worker_db_secret],
            vpc=network.vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
            security_groups=[self.db_sg],
            iam_auth=True,
            require_tls=True,
            idle_client_timeout=Duration.minutes(15),
            max_connections_percent=80,
        )

        self.logs_bucket = secure_bucket(
            self,
            "AccessLogs",
            encryption_key=None,
            removal_policy=removal,
            versioned=False,
            object_ownership=s3.ObjectOwnership.OBJECT_WRITER,  # CloudFront standard logs need ACLs
            lifecycle_rules=[s3.LifecycleRule(id="expire", expiration=Duration.days(90))],
        )
        self.raw_bucket = secure_bucket(
            self,
            "Raw",
            encryption_key=key,
            removal_policy=removal,
            access_logs=self.logs_bucket,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="bronze-retention",
                    expiration=Duration.days(cfg.raw_retention_days),
                    noncurrent_version_expiration=Duration.days(1),
                )
            ],
        )
        self.curated_bucket = secure_bucket(
            self,
            "Curated",
            encryption_key=key,
            removal_policy=removal,
            access_logs=self.logs_bucket,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="infrequent-access",
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.INFREQUENT_ACCESS,
                            transition_after=Duration.days(30),
                        )
                    ],
                    noncurrent_version_expiration=Duration.days(30),
                )
            ],
        )
        lock = (
            s3.ObjectLockRetention.compliance(Duration.days(cfg.audit_object_lock_days))
            if cfg.audit_object_lock_mode == "compliance"
            else s3.ObjectLockRetention.governance(Duration.days(cfg.audit_object_lock_days))
        )
        self.audit_bucket = secure_bucket(
            self,
            "AuditAnchors",
            encryption_key=key,
            removal_policy=removal,
            access_logs=self.logs_bucket,
            object_lock_default_retention=lock,
        )
        # DSAR access/portability exports: one subject's decrypted data for the compliance
        # team. Written (never read) by the DSAR worker; gone after 30 days.
        self.dsar_export_bucket = secure_bucket(
            self,
            "DsarExports",
            encryption_key=key,
            removal_policy=removal,
            access_logs=self.logs_bucket,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="dsar-export-expiry",
                    expiration=Duration.days(30),
                    noncurrent_version_expiration=Duration.days(1),
                )
            ],
        )

        database = glue.CfnDatabase(
            self,
            "Catalog",
            catalog_id=self.account,
            database_input=glue.CfnDatabase.DatabaseInputProperty(name=f"leadintel_{cfg.name}"),
        )
        athena.CfnWorkGroup(
            self,
            "Analytics",
            name=f"{cfg.prefix}-analytics",
            recursive_delete_option=not cfg.is_production,
            work_group_configuration=athena.CfnWorkGroup.WorkGroupConfigurationProperty(
                enforce_work_group_configuration=True,
                publish_cloud_watch_metrics_enabled=True,
                bytes_scanned_cutoff_per_query=50 * 1024**3,
                result_configuration=athena.CfnWorkGroup.ResultConfigurationProperty(
                    output_location=f"s3://{self.curated_bucket.bucket_name}/athena-results/",
                    encryption_configuration=athena.CfnWorkGroup.EncryptionConfigurationProperty(
                        encryption_option="SSE_KMS", kms_key=key.key_arn
                    ),
                ),
            ),
        ).node.add_dependency(database)

        CfnOutput(self, "ClusterEndpoint", value=self.cluster.cluster_endpoint.hostname)
        CfnOutput(self, "ProxyEndpoint", value=self.proxy.endpoint)
        CfnOutput(self, "ClusterIdentifier", value=self.cluster.cluster_identifier)
        CfnOutput(self, "RawBucketName", value=self.raw_bucket.bucket_name)
        CfnOutput(self, "CuratedBucketName", value=self.curated_bucket.bucket_name)
        CfnOutput(self, "AuditBucketName", value=self.audit_bucket.bucket_name)
        CfnOutput(self, "DsarExportBucketName", value=self.dsar_export_bucket.bucket_name)
        CfnOutput(self, "LogsBucketName", value=self.logs_bucket.bucket_name)
