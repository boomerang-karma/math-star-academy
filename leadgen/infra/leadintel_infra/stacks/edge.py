"""Edge protection: the WAF web ACL in front of CloudFront (must live in us-east-1).

Rules, in priority order
  1  rate limit on /api/collect per IP (the only unauthenticated write path)
  2  overall rate limit per IP
  3  Amazon IP reputation list
  4  common rule set (OWASP top-10 style)
  5  known bad inputs (Log4Shell & co.)
  6  SQL injection patterns (defence in depth: all queries are parameterized)
WAF logs go to CloudWatch with the Authorization and Cookie headers redacted.
"""

from __future__ import annotations

from typing import Any

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_logs as logs
from aws_cdk import aws_wafv2 as waf
from constructs import Construct

from leadintel_infra.config import EnvConfig
from leadintel_infra.constructs.python_function import retention


def _visibility(name: str) -> waf.CfnWebACL.VisibilityConfigProperty:
    return waf.CfnWebACL.VisibilityConfigProperty(
        cloud_watch_metrics_enabled=True, metric_name=name, sampled_requests_enabled=True
    )


def _managed(priority: int, name: str) -> waf.CfnWebACL.RuleProperty:
    return waf.CfnWebACL.RuleProperty(
        name=name,
        priority=priority,
        override_action=waf.CfnWebACL.OverrideActionProperty(none={}),
        statement=waf.CfnWebACL.StatementProperty(
            managed_rule_group_statement=waf.CfnWebACL.ManagedRuleGroupStatementProperty(
                vendor_name="AWS", name=name
            )
        ),
        visibility_config=_visibility(name),
    )


class EdgeStack(Stack):
    def __init__(
        self, scope: Construct, construct_id: str, *, cfg: EnvConfig, **kwargs: Any
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        removal = RemovalPolicy.RETAIN if cfg.is_production else RemovalPolicy.DESTROY

        beacon_limit = waf.CfnWebACL.RuleProperty(
            name="beacon-rate-limit",
            priority=1,
            action=waf.CfnWebACL.RuleActionProperty(block={}),
            statement=waf.CfnWebACL.StatementProperty(
                rate_based_statement=waf.CfnWebACL.RateBasedStatementProperty(
                    limit=cfg.beacon_rate_limit_per_5min,
                    aggregate_key_type="IP",
                    scope_down_statement=waf.CfnWebACL.StatementProperty(
                        byte_match_statement=waf.CfnWebACL.ByteMatchStatementProperty(
                            field_to_match=waf.CfnWebACL.FieldToMatchProperty(uri_path={}),
                            positional_constraint="STARTS_WITH",
                            search_string="/api/collect",
                            text_transformations=[
                                waf.CfnWebACL.TextTransformationProperty(
                                    priority=0, type="LOWERCASE"
                                )
                            ],
                        )
                    ),
                )
            ),
            visibility_config=_visibility("beacon-rate-limit"),
        )
        global_limit = waf.CfnWebACL.RuleProperty(
            name="ip-rate-limit",
            priority=2,
            action=waf.CfnWebACL.RuleActionProperty(block={}),
            statement=waf.CfnWebACL.StatementProperty(
                rate_based_statement=waf.CfnWebACL.RateBasedStatementProperty(
                    limit=cfg.waf_rate_limit_per_5min, aggregate_key_type="IP"
                )
            ),
            visibility_config=_visibility("ip-rate-limit"),
        )
        self.web_acl = waf.CfnWebACL(
            self,
            "WebAcl",
            name=f"{cfg.prefix}-edge",
            scope="CLOUDFRONT",
            default_action=waf.CfnWebACL.DefaultActionProperty(allow={}),
            visibility_config=_visibility(f"{cfg.prefix}-edge"),
            rules=[
                beacon_limit,
                global_limit,
                _managed(3, "AWSManagedRulesAmazonIpReputationList"),
                _managed(4, "AWSManagedRulesCommonRuleSet"),
                _managed(5, "AWSManagedRulesKnownBadInputsRuleSet"),
                _managed(6, "AWSManagedRulesSQLiRuleSet"),
            ],
        )
        # WAF requires the log group name to start with "aws-waf-logs-".
        waf_logs = logs.LogGroup(
            self,
            "WafLogs",
            log_group_name=f"aws-waf-logs-{cfg.prefix}",
            retention=retention(cfg.log_retention_days),
            removal_policy=removal,
        )
        waf.CfnLoggingConfiguration(
            self,
            "WafLogging",
            log_destination_configs=[waf_logs.log_group_arn],
            resource_arn=self.web_acl.attr_arn,
            redacted_fields=[
                waf.CfnLoggingConfiguration.FieldToMatchProperty(
                    single_header={"Name": "authorization"}
                ),
                waf.CfnLoggingConfiguration.FieldToMatchProperty(single_header={"Name": "cookie"}),
            ],
        )
        self.web_acl_arn = self.web_acl.attr_arn
        CfnOutput(self, "WebAclArn", value=self.web_acl_arn)
