import { useState } from "react";
import { Link } from "react-router-dom";

import { useApp, useResource } from "../app/context";
import { ErrorNotice, Loading } from "../components/Status";
import { formatPercent, humanize, sourceLabel } from "../lib/format";
import { EvidenceList } from "./EntityPage";

/** Entity-resolution pairs the matcher was unsure about, for a human to merge or keep apart. */
export function ReviewQueue() {
  const { api } = useApp();
  const queue = useResource(() => api.reviews(), [api]);
  const [decided, setDecided] = useState<Record<string, "accept" | "reject">>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);

  async function decide(id: string, decision: "accept" | "reject") {
    setBusy(id);
    setError(null);
    try {
      await api.decideReview(id, decision);
      setDecided((d) => ({ ...d, [id]: decision }));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(null);
    }
  }

  if (queue.loading) {
    return <Loading />;
  }
  if (queue.error || !queue.data) {
    return <ErrorNotice error={queue.error} onRetry={queue.reload} />;
  }
  const pending = queue.data.items.filter((item) => !decided[item.id]);
  const done = Object.keys(decided).length;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Review queue</h1>
          <p className="muted">
            Possible duplicates the matcher could not decide. Merging is audited and keeps every source record&apos;s
            lineage.
          </p>
        </div>
      </div>
      {error ? <ErrorNotice error={error} /> : null}
      {done > 0 ? (
        <p className="notice" role="status">
          {done} decision{done === 1 ? "" : "s"} recorded.
        </p>
      ) : null}
      {pending.length === 0 ? (
        <p className="empty">Nothing to review.</p>
      ) : (
        <ul className="review-list">
          {pending.map((item) => (
            <li key={item.id} className="card review">
              <div className="review-pair">
                <div>
                  <span className="muted small">New record ({sourceLabel(item.record_source)})</span>
                  <Link to={`/entities/${item.record_entity.id}`} className="strong">
                    {item.record_entity.name ?? item.record_entity.id.slice(0, 8)}
                  </Link>
                </div>
                <div className="review-vs" aria-hidden="true">
                  {"↔"}
                </div>
                <div>
                  <span className="muted small">Existing {humanize(item.entity_type)}</span>
                  <Link to={`/entities/${item.candidate_entity.id}`} className="strong">
                    {item.candidate_entity.name ?? item.candidate_entity.id.slice(0, 8)}
                  </Link>
                </div>
                <div className="review-prob">
                  <span className="muted small">Match probability</span>
                  <span className="strong">{formatPercent(item.probability)}</span>
                </div>
              </div>
              <EvidenceList evidence={item.evidence} />
              <div className="actions">
                <button
                  type="button"
                  className="button button-primary"
                  disabled={busy !== null}
                  onClick={() => void decide(item.id, "accept")}
                >
                  Same entity: merge
                </button>
                <button
                  type="button"
                  className="button"
                  disabled={busy !== null}
                  onClick={() => void decide(item.id, "reject")}
                >
                  Different: keep apart
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
