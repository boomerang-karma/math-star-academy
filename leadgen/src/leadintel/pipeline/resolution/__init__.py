"""Entity resolution: decide which source records describe the same real-world entity.

    records ──blocking──▶ candidate pairs ──matching──▶ scored pairs
            ──clustering (constrained union-find)──▶ entities
            ──survivorship──▶ golden records with per-attribute provenance

Design rules:

* **Explainable.** Every match carries the evidence (feature, weight, detail) that
  produced it; analysts see it in the review queue and the entity's lineage.
* **Conservative.** Existing entities are never merged automatically; strong
  identifier conflicts (two LinkedIn profiles in one cluster) block a union and
  route the pair to human review instead.
* **Non-destructive.** Source records are immutable; clusters and golden records
  can always be recomputed from them, so a bad merge is reversible.
"""
