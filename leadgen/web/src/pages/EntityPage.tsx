import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import type { Evidence, LineageEntry } from "../api/types";
import { useApp, useResource } from "../app/context";
import { GraphView } from "../components/GraphView";
import { ProvenanceTable } from "../components/ProvenanceTable";
import { SignalTimeline } from "../components/SignalTimeline";
import { ErrorNotice, Loading } from "../components/Status";
import { EMPTY, formatDate, formatPercent, formatPoints, humanize, safeHref, sourceLabel } from "../lib/format";

export function EvidenceList({ evidence }: { evidence: Evidence[] | null }) {
  if (!evidence || evidence.length === 0) {
    return <span className="muted small">No evidence recorded</span>;
  }
  return (
    <ul className="evidence">
      {evidence.map((e, i) => (
        <li key={`${e.feature}-${i}`}>
          <span className={`points ${e.weight >= 0 ? "points-pos" : "points-neg"}`}>{formatPoints(e.weight)}</span>{" "}
          <span className="strong">{humanize(e.feature)}</span> <span className="muted small">{e.detail}</span>
        </li>
      ))}
    </ul>
  );
}

function LineageTable({ lineage }: { lineage: LineageEntry[] }) {
  if (lineage.length === 0) {
    return <p className="muted">No source records linked.</p>;
  }
  return (
    <div className="table-wrap">
      <table className="table">
        <caption>Source records that resolved to this entity</caption>
        <thead>
          <tr>
            <th scope="col">Source</th>
            <th scope="col">Observed</th>
            <th scope="col">Lawful basis</th>
            <th scope="col">Match</th>
            <th scope="col">Evidence</th>
          </tr>
        </thead>
        <tbody>
          {lineage.map((r) => {
            const href = safeHref(r.source_url);
            return (
              <tr key={r.record_id}>
                <td>
                  {href ? (
                    <a href={href} target="_blank" rel="noopener noreferrer">
                      {sourceLabel(r.source)}
                    </a>
                  ) : (
                    sourceLabel(r.source)
                  )}
                  <div className="muted small mono" title={r.record_id}>
                    {r.record_id.slice(0, 8)}
                  </div>
                </td>
                <td>{formatDate(r.observed_at)}</td>
                <td>{humanize(r.lawful_basis)}</td>
                <td>
                  {humanize(r.match.method)} {formatPercent(r.match.probability)}
                  {r.match.decided_by ? <div className="muted small">by {r.match.decided_by}</div> : null}
                </td>
                <td>
                  {r.match.evidence?.length ? (
                    <details>
                      <summary>
                        {r.match.evidence.length} factor{r.match.evidence.length === 1 ? "" : "s"}
                      </summary>
                      <EvidenceList evidence={r.match.evidence} />
                    </details>
                  ) : (
                    <span className="muted small">{r.match.method === "seed" ? "First record" : EMPTY}</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function EntityPage() {
  const { id = "" } = useParams();
  const { api } = useApp();
  const [depth, setDepth] = useState<1 | 2>(1);
  const entity = useResource(() => api.entity(id), [api, id]);
  const graph = useResource(() => api.entityGraph(id, depth), [api, id, depth]);

  if (entity.loading) {
    return <Loading />;
  }
  if (entity.error || !entity.data) {
    return <ErrorNotice error={entity.error} onRetry={entity.reload} />;
  }
  const e = entity.data;
  return (
    <>
      <p className="crumbs">
        <Link to="/leads">Leads</Link> / {humanize(e.type)}
      </p>
      <div className="page-head">
        <div>
          <h1>{e.display_name ?? e.domain ?? "Unnamed entity"}</h1>
          <p className="muted">
            {[humanize(e.type), e.domain, humanize(e.status), e.updated_at ? `updated ${formatDate(e.updated_at)}` : null]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
      </div>
      {e.merged_into ? (
        <div className="notice notice-warn" role="note">
          This record was merged into <Link to={`/entities/${e.merged_into}`}>another entity</Link>.
        </div>
      ) : null}

      <div className="grid">
        {e.contact ? (
          <section className="card" aria-labelledby="contact-h">
            <h2 id="contact-h">Contact</h2>
            <dl className="facts">
              <dt>Email</dt>
              <dd className="mono">{e.contact.email ?? EMPTY}</dd>
              <dt>Phone</dt>
              <dd className="mono">{e.contact.phone ?? EMPTY}</dd>
            </dl>
            {e.contact.masked ? <p className="muted small">Masked for your role.</p> : null}
          </section>
        ) : null}

        <section className="card" aria-labelledby="signals-h">
          <h2 id="signals-h">Signals</h2>
          <SignalTimeline signals={e.signals} />
        </section>

        <section className="card span-2" aria-labelledby="graph-h">
          <div className="card-head">
            <h2 id="graph-h">Relationships</h2>
            <div className="segmented" role="group" aria-label="Graph depth">
              {([1, 2] as const).map((d) => (
                <button
                  key={d}
                  type="button"
                  className={depth === d ? "active" : ""}
                  aria-pressed={depth === d}
                  onClick={() => setDepth(d)}
                >
                  {d} hop{d === 2 ? "s" : ""}
                </button>
              ))}
            </div>
          </div>
          {graph.loading ? (
            <Loading />
          ) : graph.error || !graph.data ? (
            <ErrorNotice error={graph.error} onRetry={graph.reload} />
          ) : (
            <GraphView graph={graph.data} focusIds={[e.id]} />
          )}
        </section>

        <section className="card span-2" aria-labelledby="attrs-h">
          <h2 id="attrs-h">Golden record</h2>
          <ProvenanceTable attributes={e.attributes} caption="Surviving value per attribute, with provenance" />
        </section>

        <section className="card span-2" aria-labelledby="lineage-h">
          <h2 id="lineage-h">Lineage</h2>
          <LineageTable lineage={e.lineage} />
        </section>
      </div>
    </>
  );
}
