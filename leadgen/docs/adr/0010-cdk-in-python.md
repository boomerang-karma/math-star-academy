# 0010. AWS CDK in Python

**Status:** Accepted

## Context

Infrastructure spans ten-odd services across two regions (CloudFront's WAF
must live in us-east-1). The application is Python. We want infrastructure
reviewed and tested like code, with security posture asserted in CI.

## Decision

- **Tooling.** AWS CDK v2 in Python (`infra/`).
- **Stacks.** One stack per concern: network, security, data, ingestion, api,
  edge, web, observability, cicd. The stacks are named
  `leadintel-<env>-<unit>`.
- **Configuration.** Per-environment config in `infra/config/<env>.json`,
  validated by `EnvConfig`.
- **Tests.** `tests/infra` synthesizes the app and asserts posture: encryption,
  TLS-only buckets, private subnets, JWT on routes, no wildcard admin policies,
  alarms, and SPA caching.
- **Lifecycle.** Scripts wrap the whole cycle (`scripts/aws/`): bootstrap,
  setup, status, rotation and teardown.

## Alternatives

- **Terraform.** Mature and multi-cloud, but a second language. It also lacks
  CDK's high-level constructs (e.g. `grant_*` helpers, RDS Proxy, BucketDeployment).
- **SAM / Serverless Framework.** Good for functions, weaker for VPCs,
  databases and edge.
- **Raw CloudFormation.** Verbose, with no abstraction or tests.

## Consequences

- One language across application, infrastructure and tests.
- Cross-stack references need care to avoid dependency cycles. Grants that
  would edit another stack's key policy use identity policies instead
  (`constructs/grants.py`).
- Synthesis needs Node.js (jsii) in CI.
