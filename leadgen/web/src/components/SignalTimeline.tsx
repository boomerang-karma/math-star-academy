import type { SignalView } from "../api/types";
import { formatDate, relativeTime, safeHref, signalLabel, sourceLabel } from "../lib/format";

const INTENT = new Set([
  "job_posting",
  "funding",
  "acquisition",
  "expansion",
  "leadership_change",
  "news_mention",
  "tech_detected",
]);

export function SignalTimeline({ signals, limit = 25 }: { signals: SignalView[]; limit?: number }) {
  if (signals.length === 0) {
    return <p className="muted">No signals yet.</p>;
  }
  const ordered = [...signals].sort((a, b) => b.occurred_at.localeCompare(a.occurred_at));
  return (
    <ol className="timeline">
      {ordered.slice(0, limit).map((s) => {
        const href = safeHref(s.url);
        return (
          <li key={s.id} className={`timeline-item ${INTENT.has(s.type) ? "kind-intent" : "kind-engagement"}`}>
            <div className="timeline-meta">
              <span className="badge">{signalLabel(s.type)}</span>
              <time dateTime={s.occurred_at} title={formatDate(s.occurred_at)}>
                {relativeTime(s.occurred_at)}
              </time>
            </div>
            <div className="timeline-title">
              {href ? (
                <a href={href} target="_blank" rel="noopener noreferrer">
                  {s.title ?? signalLabel(s.type)}
                </a>
              ) : (
                (s.title ?? signalLabel(s.type))
              )}
            </div>
            <div className="muted small">
              {sourceLabel(s.source)} {"·"} strength {s.strength.toFixed(2)}
            </div>
          </li>
        );
      })}
      {ordered.length > limit ? (
        <li className="muted small">and {ordered.length - limit} older signals</li>
      ) : null}
    </ol>
  );
}
