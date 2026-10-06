# 0001. Serverless first on AWS

**Status:** Accepted

## Context

The workload is bursty:

- scheduled discovery runs
- webhook and beacon spikes
- a few dozen interactive users in business hours

Volumes are moderate (thousands to low millions of records). The team is small
and wants near-zero operations and cost that tracks usage.

## Decision

- **Compute.** AWS Lambda (arm64, Python 3.12) for the API and every worker.
- **Messaging.** SQS with dead-letter queues for event-driven paths.
- **Orchestration.** Step Functions for multi-step enrichment, and EventBridge
  for schedules.
- **Edge.** API Gateway HTTP API behind CloudFront.
- **Database.** Aurora Serverless v2.
- **Packaging.** One code bundle with many handlers, so the code is shared and
  the deployment unit is simple.

## Alternatives

- **ECS Fargate services.** Steadier latency and no 15-minute limit, but
  always-on cost and more operational surface. This remains the path for any
  job that outgrows Lambda limits.
- **EKS.** Not justified at this scale.
- **Glue/EMR for the pipeline.** Built for much larger batch volumes than these.

## Consequences

- Cost is near zero when idle, apart from fixed network and database items:
  NAT, interface endpoints and RDS Proxy (see the cost model).
- Cold starts affect the API, so production keeps two provisioned instances.
- Long enrichment is split into Step Functions tasks under the 15-minute limit.
- Database connections need pooling, so RDS Proxy is required.
