"""Web: one CloudFront distribution for the SPA (private S3) and the API (``/api/*``).

Serving both from one origin means the SPA needs no CORS, cookies never cross
sites, and a single WAF covers everything. The API behaviour adds the
``X-Origin-Verify`` header that the Lambda requires, disables caching and
forwards every viewer header except Host. A CloudFront Function rewrites SPA
routes to ``/index.html`` on the default behaviour only, so API 404s stay 404s.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_s3_deployment as s3deploy
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct

from leadintel_infra.config import EnvConfig
from leadintel_infra.constructs.secure_bucket import secure_bucket

SPA_REWRITE = """
function handler(event) {
  var request = event.request;
  var uri = request.uri;
  if (!uri.startsWith('/api/') && uri.indexOf('.') === -1) {
    request.uri = '/index.html';
  }
  return request;
}
"""


def content_security_policy(cognito_domain: str, region: str) -> str:
    return "; ".join(
        [
            "default-src 'self'",
            "script-src 'self'",
            "style-src 'self'",
            "img-src 'self' data:",
            "font-src 'self'",
            f"connect-src 'self' https://{cognito_domain} https://cognito-idp.{region}.amazonaws.com",
            f"form-action 'self' https://{cognito_domain}",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "object-src 'none'",
            "upgrade-insecure-requests",
        ]
    )


class WebStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cfg: EnvConfig,
        api_domain: str,
        web_acl_arn: str,
        origin_verify_secret: secretsmanager.ISecret,
        cognito_domain: str,
        logs_bucket: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        removal = RemovalPolicy.RETAIN if cfg.is_production else RemovalPolicy.DESTROY
        site = secure_bucket(self, "Site", encryption_key=None, removal_policy=removal)

        headers = cloudfront.ResponseHeadersPolicy(
            self,
            "SecurityHeaders",
            response_headers_policy_name=f"{cfg.prefix}-security-headers",
            security_headers_behavior=cloudfront.ResponseSecurityHeadersBehavior(
                strict_transport_security=cloudfront.ResponseHeadersStrictTransportSecurity(
                    access_control_max_age=Duration.days(730),
                    include_subdomains=True,
                    preload=True,
                    override=True,
                ),
                content_type_options=cloudfront.ResponseHeadersContentTypeOptions(override=True),
                frame_options=cloudfront.ResponseHeadersFrameOptions(
                    frame_option=cloudfront.HeadersFrameOption.DENY, override=True
                ),
                referrer_policy=cloudfront.ResponseHeadersReferrerPolicy(
                    referrer_policy=cloudfront.HeadersReferrerPolicy.NO_REFERRER, override=True
                ),
                content_security_policy=cloudfront.ResponseHeadersContentSecurityPolicy(
                    content_security_policy=content_security_policy(cognito_domain, self.region),
                    override=True,
                ),
            ),
            custom_headers_behavior=cloudfront.ResponseCustomHeadersBehavior(
                custom_headers=[
                    cloudfront.ResponseCustomHeader(
                        header="Permissions-Policy",
                        value="camera=(), microphone=(), geolocation=()",
                        override=True,
                    ),
                ]
            ),
        )
        rewrite = cloudfront.Function(
            self,
            "SpaRewrite",
            code=cloudfront.FunctionCode.from_inline(SPA_REWRITE),
            runtime=cloudfront.FunctionRuntime.JS_2_0,
        )
        api_origin = origins.HttpOrigin(
            api_domain,
            protocol_policy=cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
            origin_ssl_protocols=[cloudfront.OriginSslPolicy.TLS_V1_2],
            # A CloudFormation dynamic reference: resolved at deploy time, never in the template.
            custom_headers={"X-Origin-Verify": origin_verify_secret.secret_value.unsafe_unwrap()},
        )
        certificate = (
            acm.Certificate.from_certificate_arn(self, "Certificate", cfg.certificate_arn)
            if cfg.certificate_arn
            else None
        )
        self.distribution = cloudfront.Distribution(
            self,
            "Distribution",
            comment=f"{cfg.prefix} web + api",
            default_root_object="index.html",
            minimum_protocol_version=cloudfront.SecurityPolicyProtocol.TLS_V1_2_2021,
            http_version=cloudfront.HttpVersion.HTTP2_AND_3,
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            web_acl_id=web_acl_arn,
            domain_names=[cfg.domain_name] if cfg.domain_name and certificate else None,
            certificate=certificate,
            enable_logging=True,
            log_bucket=logs_bucket,
            log_file_prefix="cloudfront/",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(site),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                response_headers_policy=headers,
                function_associations=[
                    cloudfront.FunctionAssociation(
                        function=rewrite, event_type=cloudfront.FunctionEventType.VIEWER_REQUEST
                    )
                ],
            ),
            additional_behaviors={
                "/api/*": cloudfront.BehaviorOptions(
                    origin=api_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                ),
            },
        )

        # web_asset_dir is relative to infra/ (default ../web/dist, built by `npm run build`).
        asset_dir = (Path(__file__).resolve().parents[2] / cfg.web_asset_dir).resolve()
        if asset_dir.exists():
            s3deploy.BucketDeployment(
                self,
                "DeploySpa",
                sources=[s3deploy.Source.asset(str(asset_dir))],
                destination_bucket=site,
                distribution=self.distribution,
                distribution_paths=["/index.html"],
                prune=True,
                memory_limit=512,
            )

        CfnOutput(
            self,
            "Url",
            value=f"https://{cfg.domain_name or self.distribution.distribution_domain_name}",
        )
        CfnOutput(self, "DistributionId", value=self.distribution.distribution_id)
        CfnOutput(self, "SiteBucketName", value=site.bucket_name)
