/**
 * Deterministic radial tree layout for small relationship graphs.
 *
 * Focus entities sit in the centre. Every other node is placed on a ring by its
 * hop distance from the focus (breadth-first), inside the angular sector of the
 * node it was reached from, with sectors sized by how many leaves they hold. So
 * a company's people cluster around that company and edges do not cut across
 * the focus. The output is plain coordinates: the SVG needs no inline styles
 * (CSP-safe) and the layout is testable without a browser.
 */

import type { Graph, GraphNode } from "../api/types";

export interface PlacedNode extends GraphNode {
  x: number;
  y: number;
  depth: number;
}

export interface PlacedEdge {
  id: string;
  type: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface Layout {
  width: number;
  height: number;
  nodes: PlacedNode[];
  edges: PlacedEdge[];
}

const ROOT = "\u0000root";

function compareNodes(a: GraphNode, b: GraphNode): number {
  return (
    a.type.localeCompare(b.type) ||
    (a.label ?? "").localeCompare(b.label ?? "") ||
    a.id.localeCompare(b.id)
  );
}

interface Indexed {
  nodes: Map<string, GraphNode>;
  adjacency: Map<string, string[]>;
  sortIds: (ids: Iterable<string>) => string[];
}

function index(graph: Graph): Indexed {
  const nodes = new Map(graph.nodes.map((n) => [n.id, n]));
  const sortIds = (ids: Iterable<string>) =>
    [...new Set(ids)].sort((a, b) => compareNodes(nodes.get(a) as GraphNode, nodes.get(b) as GraphNode));
  const adjacency = new Map<string, string[]>();
  for (const e of graph.edges) {
    if (nodes.has(e.source) && nodes.has(e.target) && e.source !== e.target) {
      adjacency.set(e.source, [...(adjacency.get(e.source) ?? []), e.target]);
      adjacency.set(e.target, [...(adjacency.get(e.target) ?? []), e.source]);
    }
  }
  for (const [id, list] of adjacency) {
    adjacency.set(id, sortIds(list));
  }
  return { nodes, adjacency, sortIds };
}

/** Breadth-first search from `roots`, recording depth and the tree edge that reached each node. */
function bfs(
  g: Indexed,
  roots: string[],
  rootDepth: number,
  depth: Map<string, number>,
  children: Map<string, string[]>,
): void {
  const queue = roots.filter((id) => !depth.has(id));
  for (const id of queue) {
    depth.set(id, rootDepth);
    children.set(ROOT, [...(children.get(ROOT) ?? []), id]);
  }
  for (let head = 0; head < queue.length; head++) {
    const current = queue[head] as string;
    for (const next of g.adjacency.get(current) ?? []) {
      if (!depth.has(next)) {
        depth.set(next, (depth.get(current) ?? 0) + 1);
        children.set(current, [...(children.get(current) ?? []), next]);
        queue.push(next);
      }
    }
  }
}

/** Hop distance from the nearest focus node, for every node reachable from the focus. */
export function hopDistances(graph: Graph, focusIds: readonly string[]): Map<string, number> {
  const g = index(graph);
  const depth = new Map<string, number>();
  bfs(g, g.sortIds(focusIds.filter((id) => g.nodes.has(id))), 0, depth, new Map());
  return depth;
}

export function radialLayout(
  graph: Graph,
  focusIds: readonly string[],
  size: { width: number; height: number } = { width: 640, height: 420 },
): Layout {
  const { width, height } = size;
  const margin = 48;
  const cx = width / 2;
  const cy = height / 2;

  // Spanning forest: the focus first, then each unconnected component on an outer ring.
  const g = index(graph);
  const depth = new Map<string, number>();
  const children = new Map<string, string[]>();
  const focus = g.sortIds(focusIds.filter((id) => g.nodes.has(id)));
  bfs(g, focus, 0, depth, children);
  const outer = depth.size ? Math.max(...depth.values()) + 1 : 0;
  for (const id of g.sortIds(g.nodes.keys())) {
    bfs(g, [id], outer, depth, children);
  }

  const leaves = new Map<string, number>();
  const countLeaves = (id: string): number => {
    const kids = children.get(id) ?? [];
    const total = kids.length ? kids.reduce((sum, kid) => sum + countLeaves(kid), 0) : 1;
    leaves.set(id, total);
    return total;
  };
  countLeaves(ROOT);

  const centred = focus.length === 1;
  const maxDepth = Math.max(0, ...depth.values());
  const maxRadius = Math.max(0, Math.min(width, height) / 2 - margin);
  const inner = centred ? 0 : Math.min(maxRadius / (maxDepth + 2), 60);
  const step = maxDepth > 0 ? (maxRadius - inner) / maxDepth : 0;

  const placed: PlacedNode[] = [];
  const place = (parent: string, from: number, to: number) => {
    let start = from;
    for (const id of children.get(parent) ?? []) {
      const share = ((to - from) * (leaves.get(id) ?? 1)) / (leaves.get(parent) ?? 1);
      const d = depth.get(id) ?? 0;
      const r = d === 0 ? inner : inner + d * step;
      const angle = start + share / 2;
      placed.push({
        ...(g.nodes.get(id) as GraphNode),
        depth: d,
        x: round(cx + r * Math.cos(angle)),
        y: round(cy + r * Math.sin(angle)),
      });
      place(id, start, start + share);
      start += share;
    }
  };
  place(ROOT, -Math.PI / 2, (3 * Math.PI) / 2);

  const at = new Map(placed.map((n) => [n.id, n]));
  const edges: PlacedEdge[] = [];
  for (const e of graph.edges) {
    const a = at.get(e.source);
    const b = at.get(e.target);
    if (a && b && a !== b) {
      edges.push({ id: e.id, type: e.type, x1: a.x, y1: a.y, x2: b.x, y2: b.y });
    }
  }
  return { width, height, nodes: placed, edges };
}

function round(value: number): number {
  return Math.round(value * 10) / 10;
}
