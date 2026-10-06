"""Deployment units, in dependency order.

=================  ===========================================================================
Stack              Contents
=================  ===========================================================================
network            VPC (public / private / isolated tiers), NAT, endpoints, flow logs
security           KMS keys, application secrets, Cognito, optional account guardrails
data               Aurora PostgreSQL Serverless v2, RDS Proxy, S3 zones, Athena workgroup
ingestion          SQS, worker Lambdas, Step Functions enrichment flow, schedules
api                FastAPI Lambda behind an HTTP API with a Cognito JWT authorizer
edge (us-east-1)   WAF web ACL for CloudFront
web                CloudFront + private S3 for the SPA, ``/api/*`` routed to the API
observability      alarms, dashboard, budget
cicd (once)        GitHub OIDC provider + least-privilege deploy role
=================  ===========================================================================
"""
