# 0003. Ontology with per-attribute provenance and survivorship

**Status:** Accepted

## Context

The same company or person arrives from many sources with conflicting values of
varying freshness and trust. Sales needs one answer per attribute, and needs to
know where it came from. Compliance needs lineage back to the raw source. We
want the "single pane" experience of platforms like Palantir Foundry without
adopting such a platform.

## Decision

Model the domain as an ontology (`src/leadintel/ontology`):

- **Object types:** organization, person.
- **Typed links** with their own provenance.
- **Time-stamped signals.**
- **Immutable source records** carrying lawful basis and content hash.
- **A golden record** per entity, where each attribute holds its surviving
  value, source, observation time, confidence, agreeing sources and the
  alternatives it beat.

Survivorship is deterministic: source trust (per attribute) × recency decay,
plus a bonus for agreement. Every asserted value is kept for replay.

## Alternatives

- **Last-write-wins merge into one row.** Simple, but loses provenance and
  makes conflicts invisible.
- **A commercial MDM or data platform.** Powerful, but heavy, costly and
  opinionated for this scope.
- **Keeping sources separate and merging in the UI.** Pushes complexity into
  every consumer.

## Consequences

- Every value in the UI is explainable and traceable to a source record and its
  raw payload.
- Survivorship rules can change and be recomputed from stored assertions.
- Storage grows with assertions. Retention policies bound it.
