import { describe, expect, it } from "vitest";

import type { Graph } from "../api/types";
import { hopDistances, radialLayout } from "./graphLayout";

const graph: Graph = {
  nodes: [
    { id: "org", type: "organization", label: "Northwind" },
    { id: "p1", type: "person", label: "Jordan Lee" },
    { id: "p2", type: "person", label: "Sam Patel" },
    { id: "parent", type: "organization", label: "Northwind Holdings" },
    { id: "far", type: "person", label: "Alex Kim" },
    { id: "lonely", type: "organization", label: "Unrelated" },
  ],
  edges: [
    { id: "e1", source: "p1", target: "org", type: "works_at", properties: {}, provenance: "x", confidence: 1 },
    { id: "e2", source: "p2", target: "org", type: "works_at", properties: {}, provenance: "x", confidence: 1 },
    { id: "e3", source: "org", target: "parent", type: "subsidiary_of", properties: {}, provenance: "x", confidence: 1 },
    { id: "e4", source: "far", target: "parent", type: "works_at", properties: {}, provenance: "x", confidence: 1 },
    { id: "dangling", source: "org", target: "missing", type: "works_at", properties: {}, provenance: "x", confidence: 1 },
  ],
};

describe("graph layout", () => {
  it("computes hop distances from the focus and ignores dangling edges", () => {
    const depth = hopDistances(graph, ["org"]);
    expect(Object.fromEntries(depth)).toEqual({ org: 0, p1: 1, p2: 1, parent: 1, far: 2 });
  });

  it("puts a single focus node in the centre and others on rings by distance", () => {
    const layout = radialLayout(graph, ["org"], { width: 600, height: 400 });
    const at = Object.fromEntries(layout.nodes.map((n) => [n.id, n]));
    expect(at["org"]).toMatchObject({ x: 300, y: 200, depth: 0 });
    const radius = (id: string) => Math.hypot((at[id]?.x ?? 0) - 300, (at[id]?.y ?? 0) - 200);
    expect(radius("p1")).toBeCloseTo(radius("p2"), 0);
    expect(radius("far")).toBeGreaterThan(radius("p1"));
    expect(radius("lonely")).toBeGreaterThan(radius("far"));
  });

  it("keeps every node inside the canvas with distinct positions", () => {
    const layout = radialLayout(graph, ["org", "p1"], { width: 640, height: 420 });
    const seen = new Set<string>();
    for (const n of layout.nodes) {
      expect(n.x).toBeGreaterThanOrEqual(0);
      expect(n.x).toBeLessThanOrEqual(640);
      expect(n.y).toBeGreaterThanOrEqual(0);
      expect(n.y).toBeLessThanOrEqual(420);
      seen.add(`${n.x},${n.y}`);
    }
    expect(seen.size).toBe(layout.nodes.length);
    expect(layout.edges.map((e) => e.id)).toEqual(["e1", "e2", "e3", "e4"]);
  });

  it("keeps a chain's leaves around their parent instead of across the focus", () => {
    // person -> org -> {colleague, duplicate}: the 2-hop view that used to collapse into a line.
    const chain: Graph = {
      nodes: [
        { id: "me", type: "person", label: "Jordan Lee" },
        { id: "org", type: "organization", label: "Northwind" },
        { id: "a", type: "person", label: "Avery Quinn" },
        { id: "b", type: "person", label: "Jordan Lee" },
      ],
      edges: [
        { id: "1", source: "me", target: "org", type: "works_at", properties: {}, provenance: "x", confidence: 1 },
        { id: "2", source: "a", target: "org", type: "works_at", properties: {}, provenance: "x", confidence: 1 },
        { id: "3", source: "b", target: "org", type: "works_at", properties: {}, provenance: "x", confidence: 1 },
      ],
    };
    const layout = radialLayout(chain, ["me"], { width: 600, height: 400 });
    const centre = layout.nodes.find((n) => n.id === "me");
    expect(centre).toMatchObject({ x: 300, y: 200 });
    for (const e of layout.edges.filter((edge) => edge.id !== "1")) {
      expect(distanceToSegment(300, 200, e)).toBeGreaterThan(40);
    }
  });

  it("is deterministic", () => {
    const shuffled: Graph = { nodes: [...graph.nodes].reverse(), edges: [...graph.edges].reverse() };
    const a = radialLayout(graph, ["org"]).nodes.map((n) => [n.id, n.x, n.y]).sort();
    const b = radialLayout(shuffled, ["org"]).nodes.map((n) => [n.id, n.x, n.y]).sort();
    expect(a).toEqual(b);
  });

  it("handles an empty graph", () => {
    expect(radialLayout({ nodes: [], edges: [] }, []).nodes).toEqual([]);
  });
});

function distanceToSegment(px: number, py: number, e: { x1: number; y1: number; x2: number; y2: number }): number {
  const dx = e.x2 - e.x1;
  const dy = e.y2 - e.y1;
  const t = Math.max(0, Math.min(1, ((px - e.x1) * dx + (py - e.y1) * dy) / (dx * dx + dy * dy || 1)));
  return Math.hypot(px - (e.x1 + t * dx), py - (e.y1 + t * dy));
}
