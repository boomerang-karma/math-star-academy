import { Link } from "react-router-dom";

import type { Graph } from "../api/types";
import { radialLayout } from "../lib/graphLayout";
import { humanize } from "../lib/format";

const LABEL_LIMIT = 22;

function shorten(label: string): string {
  return label.length > LABEL_LIMIT ? `${label.slice(0, LABEL_LIMIT - 1)}…` : label;
}

/** The entity neighbourhood: focus in the middle, related people and companies around it. */
export function GraphView({ graph, focusIds }: { graph: Graph; focusIds: string[] }) {
  if (graph.nodes.length === 0) {
    return <p className="muted">No relationships yet.</p>;
  }
  const layout = radialLayout(graph, focusIds);
  const focus = new Set(focusIds);
  // Label relationships only while the picture stays readable.
  const showEdgeLabels = layout.edges.length <= 12;
  const longEnough = (e: { x1: number; y1: number; x2: number; y2: number }) =>
    Math.hypot(e.x2 - e.x1, e.y2 - e.y1) >= 110;
  return (
    <figure className="graph">
      <svg
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        role="img"
        aria-label={`Relationship graph with ${layout.nodes.length} entities and ${layout.edges.length} relationships`}
      >
        <g className="graph-edges">
          {layout.edges.map((e) => (
            <g key={e.id}>
              <line x1={e.x1} y1={e.y1} x2={e.x2} y2={e.y2} className={`edge edge-${e.type}`}>
                <title>{humanize(e.type)}</title>
              </line>
              {showEdgeLabels && longEnough(e) ? (
                <text x={(e.x1 + e.x2) / 2} y={(e.y1 + e.y2) / 2 - 4} className="edge-label">
                  {humanize(e.type)}
                </text>
              ) : null}
            </g>
          ))}
        </g>
        <g className="graph-nodes">
          {layout.nodes.map((n) => {
            const label = n.label ?? n.id.slice(0, 8);
            return (
              <Link key={n.id} to={`/entities/${n.id}`} aria-label={`${humanize(n.type)}: ${label}`}>
                <g className={`node node-${n.type}${focus.has(n.id) ? " node-focus" : ""}`}>
                  <circle cx={n.x} cy={n.y} r={n.type === "organization" ? 14 : 10} />
                  <text x={n.x} y={n.y + (n.type === "organization" ? 30 : 26)} textAnchor="middle">
                    {shorten(label)}
                  </text>
                  <title>{label}</title>
                </g>
              </Link>
            );
          })}
        </g>
      </svg>
      <figcaption className="legend">
        <span className="legend-item legend-organization">Organization</span>
        <span className="legend-item legend-person">Person</span>
        <span className="muted small">Select a node to open its record.</span>
      </figcaption>
    </figure>
  );
}
