# 0005. ScrapeBadger first, behind an anti-corruption layer

**Status:** Accepted

## Context

We need broad, fresh coverage of companies and market signals:

- LinkedIn company pages and job postings
- Google Maps, Search and News
- company websites

Building and maintaining scrapers in-house means fighting anti-bot systems and
layout changes. ScrapeBadger offers these as one credit-based API with an
official Python SDK. Vendor APIs change, and so may vendors.

## Decision

- Use ScrapeBadger as the first collection source, through the official SDK
  pinned to a minor version.
- Wrap it in an anti-corruption layer
  (`connectors/scrapebadger/gateway.py` + `mappers.py`) that:
  - translates SDK models into ontology objects with pure mappers
  - maps vendor errors onto our error types (budget, rate limit, not found,
    retryable)
  - charges a per-run credit budget before each call and caps concurrency
- Expose business **playbooks** (hiring scan, company profile, news triggers,
  ...) rather than raw endpoints.
- **People.** Individual LinkedIn profiles are behind a compliance flag that is
  off by default. LinkedIn person data comes through official channels: Lead
  Gen Forms via the Lead Sync API.

## Alternatives

- **In-house scrapers.** High maintenance, legal and operational risk.
- **Other data vendors** (enrichment databases). A complementary option
  later. Each becomes another connector behind the same contract.
- **LinkedIn's official APIs for company and people data.** Access is
  restricted to approved partner programs. We use Lead Sync where we qualify.

## Consequences

- Swapping or adding a vendor touches one connector module and its contract
  tests. Nothing downstream changes.
- Cost is predictable per run, and alarms catch runaway credit burn.
- Vendor terms and data-protection obligations still apply. See
  [COMPLIANCE.md](../COMPLIANCE.md#scraping-policy).
