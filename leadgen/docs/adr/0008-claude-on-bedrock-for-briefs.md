# 0008. Claude on Amazon Bedrock for account briefs

**Status:** Accepted

## Context

Reps want a short, specific brief per account: who they are, why now, what to
say, the risks, and a next step. It should be grounded in the signals we hold.
The platform runs on AWS and processes personal data, so data flow and vendor
footprint matter.

## Decision

Generate briefs with Claude (Opus 5.5 by default) on Amazon Bedrock through
the Anthropic SDK's Bedrock client, authenticated by the Lambda's IAM role:

- **Grounded output.** Briefs come back through a tool call validated against
  a Pydantic schema, with one retry. Every "why now" item must name its signal.
- **Untrusted input.** Scraped text is fenced as untrusted data. The model has
  no tools that act.
- **Data minimization.** No names or contact details are sent, only
  firmographics, signals, score factors and the person's title and seniority.
- **Cost.** The system prompt is a cache-stable prefix. Briefs are cached per
  input fingerprint, so repeated views cost nothing.
- **Refusals** fall back to the configured fallback model client-side.

## Alternatives

- **The Claude API directly.** It gets new features first, but adds a vendor
  outside the AWS boundary and an API key to manage.
- **Smaller or self-hosted models.** Lower quality for synthesis, plus more
  to operate.
- **No AI.** The score explanation already covers "why". The brief is an
  accelerator, not a dependency, and the feature is configurable per
  environment.

## Consequences

- Data stays within AWS under IAM.
- Cost is predictable per brief (see the cost model). Briefs are labelled
  AI-generated and must be verified by the rep.
- Feature availability on Bedrock can lag the Claude API. The code avoids
  features Bedrock lacks.
