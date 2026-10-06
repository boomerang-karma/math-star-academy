# 0002. Aurora PostgreSQL as system of record and graph store

**Status:** Accepted

## Context

LeadIntel needs transactional storage for leads and users, a graph of entities
and relationships with provenance, territory-scoped access control, an
append-only audit log, and full-text/fuzzy search. The graph is small by graph
standards: millions of edges at most, and queries are 1-2 hop neighbourhoods.

## Decision

Use Aurora PostgreSQL 16 (Serverless v2) for everything:

- **Entities and links.** Entities are rows with JSONB golden records.
  Relationships are an indexed edge table. Neighbourhoods are recursive or
  joined queries.
- **Fuzzy search.** `pg_trgm` indexes.
- **Security in the database.** Row-level security, `SECURITY DEFINER`
  functions for merges, and triggers for the audit hash chain.
- **Similarity (optional).** `pgvector` (migration `V0009`).

## Alternatives

- **Amazon Neptune.** A native graph, but the leads, RLS, the audit log and the
  transactional joins would still need PostgreSQL. Running two databases means
  dual writes and consistency problems.
- **DynamoDB.** Excellent at scale and cheap, but access patterns for lineage
  and ad-hoc review are relational, and there is no row-level security.
- **OpenSearch for search.** Unnecessary while `pg_trgm` meets the need.

## Consequences

- One transactional boundary, and one place to enforce security.
- Graph analytics beyond a few hops should run off the curated S3 zone (Athena),
  or Neptune if it becomes a real need.
- Aurora Serverless v2 scales compute automatically. Dev can auto-pause at 0
  ACUs, but RDS Proxy has a fixed minimum cost.
