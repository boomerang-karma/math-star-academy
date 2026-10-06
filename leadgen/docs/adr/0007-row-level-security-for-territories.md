# 0007. Territory scoping with PostgreSQL row-level security

**Status:** Accepted

## Context

Sales reps may see only leads in their territories, or leads assigned to them,
and the people attached to those leads. Analysts and compliance work across
territories. Scoping implemented as `WHERE` clauses in application queries is
one forgotten clause away from a data leak.

## Decision

Enforce row scope in PostgreSQL with row-level security on:

- `sales.lead`
- `graph.entity`
- person `ingest.source_record`s

The API sets the caller's identity per transaction with
`set_config(..., is_local => true)`: user id, scope (`global` or `territory`)
and territory ids. Policies read these settings through `app.*` functions. The
API's database role cannot bypass RLS. Workers use a separate role with
cross-territory rights.

## Alternatives

- **Application-level filters.** Fragile, and every new query must remember
  them.
- **A schema or database per territory.** Heavy, and breaks cross-territory
  analytics and resolution.

## Consequences

- A query bug cannot widen access. The integration tests assert what each role
  sees.
- Transaction-local settings make pooled connections (RDS Proxy) safe: scope
  never leaks between requests.
- Policies cost some query performance. The relevant columns are indexed.
