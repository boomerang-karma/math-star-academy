"""Constrained clustering: turn scored pairs into entity assignments.

Matches are applied strongest-first with union-find. Two constraints keep
transitive chaining (A~B, B~C, but A!~C) from producing bad merges:

1. a cluster may contain at most one *existing* entity - merging two known
   entities is a human decision (review queue + ``graph.merge_entities``);
2. a cluster may not hold two different values of an exclusive identifier
   (two LinkedIn profiles or two LinkedIn company pages are not allowed to meet
   through a third record). Emails are deliberately *not* exclusive: people
   legitimately use a work and a personal address.

A blocked union, and every pair in the review band, becomes a review item.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from leadintel.pipeline.resolution.blocking import blocking_keys, is_strong
from leadintel.pipeline.resolution.matching import Decision, MatchResult, Thresholds, compare
from leadintel.pipeline.resolution.model import EntitySnapshot, ResolvableRecord
from leadintel.security.blind_index import BlindIndexer

MAX_WEAK_BLOCK = 50  # weak-key blocks larger than this are too generic to compare


def _exclusive_values(item: ResolvableRecord | EntitySnapshot) -> dict[str, set[str]]:
    values: dict[str, set[str]] = defaultdict(set)
    if slug := item.attributes.get("linkedin_slug"):
        values[f"{item.entity_type.value}.linkedin_slug"].add(str(slug))
    return values


@dataclass
class _Cluster:
    root: int
    existing: UUID | None
    exclusive: dict[str, set[str]]


@dataclass(frozen=True)
class ReviewItem:
    record_id: UUID
    candidate_entity_id: UUID
    result: MatchResult


@dataclass
class ResolutionOutcome:
    assignments: dict[UUID, UUID] = field(default_factory=dict)  # record -> entity
    created: dict[UUID, list[UUID]] = field(default_factory=dict)  # new entity -> records
    evidence: dict[UUID, MatchResult | None] = field(default_factory=dict)  # record -> why
    reviews: list[ReviewItem] = field(default_factory=list)
    skipped_blocks: list[str] = field(default_factory=list)


class _UnionFind:
    def __init__(self, nodes: Sequence[ResolvableRecord | EntitySnapshot]) -> None:
        self.parent = list(range(len(nodes)))
        self.clusters = {
            i: _Cluster(
                root=i,
                existing=node.entity_id if isinstance(node, EntitySnapshot) else None,
                exclusive=_exclusive_values(node),
            )
            for i, node in enumerate(nodes)
        }

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def can_union(self, i: int, j: int) -> bool:
        a, b = self.clusters[self.find(i)], self.clusters[self.find(j)]
        if a.existing and b.existing and a.existing != b.existing:
            return False
        for key in set(a.exclusive) & set(b.exclusive):
            if len(a.exclusive[key] | b.exclusive[key]) > 1:
                return False
        return True

    def union(self, i: int, j: int) -> None:
        ri, rj = self.find(i), self.find(j)
        if ri == rj:
            return
        a, b = self.clusters.pop(ri), self.clusters[rj]
        self.parent[ri] = rj
        b.existing = b.existing or a.existing
        for key, values in a.exclusive.items():
            b.exclusive.setdefault(key, set()).update(values)


def resolve(
    records: Sequence[ResolvableRecord],
    existing: Iterable[EntitySnapshot],
    *,
    bidx: BlindIndexer,
    thresholds: Thresholds = Thresholds(),
    new_id: Callable[[], UUID] = uuid4,
) -> ResolutionOutcome:
    nodes: list[ResolvableRecord | EntitySnapshot] = list(records)
    nodes.extend(existing)
    n_records = len(records)
    outcome = ResolutionOutcome()

    blocks: dict[str, list[int]] = defaultdict(list)
    for index, node in enumerate(nodes):
        for key in blocking_keys(node, bidx):
            blocks[key].append(index)

    pairs: set[tuple[int, int]] = set()
    for key, members in blocks.items():
        if len(members) < 2:
            continue
        if not is_strong(key) and len(members) > MAX_WEAK_BLOCK:
            outcome.skipped_blocks.append(key)
            continue
        for x, i in enumerate(members):
            for j in members[x + 1 :]:
                if i >= n_records and j >= n_records:
                    continue  # never auto-compare two existing entities
                if nodes[i].entity_type is not nodes[j].entity_type:
                    continue
                pairs.add((min(i, j), max(i, j)))

    scored = [(compare(nodes[i], nodes[j], thresholds), i, j) for i, j in pairs]
    scored.sort(key=lambda item: -item[0].probability)

    uf = _UnionFind(nodes)
    best: dict[int, MatchResult] = {}
    deferred: list[tuple[MatchResult, int, int]] = []
    for result, i, j in scored:
        if result.decision is Decision.MATCH and uf.can_union(i, j):
            uf.union(i, j)
            for k in (i, j):
                if k < n_records and (k not in best or best[k].probability < result.probability):
                    best[k] = result
        elif result.decision is not Decision.NO_MATCH:
            deferred.append((result, i, j))

    root_entity: dict[int, UUID] = {}
    for index in range(len(nodes)):
        root = uf.find(index)
        if root in root_entity:
            continue
        cluster = uf.clusters[root]
        root_entity[root] = cluster.existing or new_id()

    for index, record in enumerate(records):
        entity_id = root_entity[uf.find(index)]
        outcome.assignments[record.record_id] = entity_id
        outcome.evidence[record.record_id] = best.get(index)
        is_new = not uf.clusters[uf.find(index)].existing
        if is_new:
            outcome.created.setdefault(entity_id, []).append(record.record_id)

    seen: set[tuple[UUID, UUID]] = set()
    for result, i, j in deferred:
        ei, ej = root_entity[uf.find(i)], root_entity[uf.find(j)]
        if ei == ej:
            continue  # resolved through a stronger path
        for record_index, other_entity in ((i, ej), (j, ei)):
            if record_index >= n_records:
                continue
            record_id = records[record_index].record_id
            if (record_id, other_entity) in seen:
                continue
            seen.add((record_id, other_entity))
            outcome.reviews.append(ReviewItem(record_id, other_entity, result))
            break
    return outcome
