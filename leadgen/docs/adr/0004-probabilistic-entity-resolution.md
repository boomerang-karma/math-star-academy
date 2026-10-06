# 0004. Probabilistic entity resolution with a human review queue

**Status:** Accepted

## Context

Records about the same company or person rarely share a perfect key. Domains
differ (subsidiaries), names vary (legal suffixes, nicknames), people change
jobs. Wrong merges are worse than missed ones: they mix two people's data,
which is both a privacy problem and a trust problem.

## Decision

`pipeline/resolution/` resolves records in four steps:

1. **Blocking keys.** Domains, LinkedIn slugs, place ids, phone numbers and
   normalized names. Person keys are HMAC blind indexes.
2. **Fellegi-Sunter-style matching.** Every feature adds log-odds evidence, and
   the evidence list is stored with each decision.
3. **Constrained union-find clustering:**
   - at or above 0.95, the record joins the entity
   - between 0.70 and 0.95, the pair goes to the review queue
   - exclusive identifiers (two different LinkedIn slugs) veto a match
   - two existing entities are never merged automatically
4. **Merges by people.** Humans merge through one audited database function
   (`graph.merge_entities`).

## Alternatives

- **Deterministic rules only.** Precise but misses most real matches.
- **ML resolution (e.g. Splink, or a trained classifier).** Better recall with
  labels, but there are no labels yet. Review decisions will produce them
  (roadmap phase 3), and the evidence features are already the right inputs.
- **Vendor identity resolution.** Opaque, costly, and sends personal data to
  another processor.

## Consequences

- Every match is explainable (feature, weight, detail), which the UI shows in
  lineage and the review queue.
- Analysts carry a review workload. Thresholds and features are tuned from
  their decisions.
- Throughput is bounded by block sizes. Keys are selective by design.
