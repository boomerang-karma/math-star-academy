"""Network: three subnet tiers, NAT egress with stable IPs, private AWS endpoints, flow logs.

* public    - NAT gateways only. Nothing else is internet-facing (CloudFront and
              API Gateway are managed services outside the VPC).
* app       - Lambdas. Egress through NAT; the NAT Elastic IPs are exported so the
              ScrapeBadger key can be IP-restricted to them.
* data      - Aurora and RDS Proxy. No route to the internet at all.

Interface endpoints keep traffic to Secrets Manager, KMS, SQS, STS, CloudWatch
Logs and Step Functions on the AWS network (and work even if NAT is down).
"""

from __future__ import annotations

from typing import Any

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_logs as logs
from constructs import Construct

from leadintel_infra.config import EnvConfig
from leadintel_infra.constructs.python_function import retention


class NetworkStack(Stack):
    def __init__(
        self, scope: Construct, construct_id: str, *, cfg: EnvConfig, **kwargs: Any
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        removal = RemovalPolicy.RETAIN if cfg.is_production else RemovalPolicy.DESTROY

        flow_logs = logs.LogGroup(
            self, "FlowLogs", retention=retention(cfg.log_retention_days), removal_policy=removal
        )
        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            ip_addresses=ec2.IpAddresses.cidr(cfg.vpc_cidr),
            max_azs=cfg.max_azs,
            nat_gateways=cfg.nat_gateways,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24
                ),
                ec2.SubnetConfiguration(
                    name="app", subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS, cidr_mask=22
                ),
                ec2.SubnetConfiguration(
                    name="data", subnet_type=ec2.SubnetType.PRIVATE_ISOLATED, cidr_mask=24
                ),
            ],
            flow_logs={
                "all": ec2.FlowLogOptions(
                    destination=ec2.FlowLogDestination.to_cloud_watch_logs(flow_logs),
                    traffic_type=ec2.FlowLogTrafficType.ALL,
                )
            },
            restrict_default_security_group=True,
        )

        self.vpc.add_gateway_endpoint("S3", service=ec2.GatewayVpcEndpointAwsService.S3)
        endpoint_sg = ec2.SecurityGroup(
            self,
            "EndpointSg",
            vpc=self.vpc,
            description="Interface endpoints",
            allow_all_outbound=False,
        )
        endpoint_sg.add_ingress_rule(
            ec2.Peer.ipv4(cfg.vpc_cidr), ec2.Port.tcp(443), "HTTPS from VPC"
        )
        for name, service in {
            "SecretsManager": ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
            "Kms": ec2.InterfaceVpcEndpointAwsService.KMS,
            "Sqs": ec2.InterfaceVpcEndpointAwsService.SQS,
            "Sts": ec2.InterfaceVpcEndpointAwsService.STS,
            "Logs": ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
            "StepFunctions": ec2.InterfaceVpcEndpointAwsService.STEP_FUNCTIONS,
        }.items():
            self.vpc.add_interface_endpoint(
                name,
                service=service,
                subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
                security_groups=[endpoint_sg],
                private_dns_enabled=True,
            )

        self.lambda_sg = ec2.SecurityGroup(
            self, "LambdaSg", vpc=self.vpc, description="Platform Lambdas", allow_all_outbound=True
        )
        # The database security group lives in the data stack (next to the cluster it
        # guards) to avoid a network <-> data reference cycle through RDS Proxy rules.

        for index, subnet in enumerate(self.vpc.public_subnets):
            eip = subnet.node.try_find_child("EIP")
            if isinstance(eip, ec2.CfnEIP):
                CfnOutput(
                    self,
                    f"NatEgressIp{index + 1}",
                    value=eip.attr_public_ip,
                    description="Allow-list this IP on the ScrapeBadger API key",
                )
