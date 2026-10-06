import type { Contribution } from "../api/types";
import { formatPoints, humanize } from "../lib/format";

const ORDER = ["fit", "intent", "engagement"];

/** Every point in the score, by component, with the reason the model gave it. */
export function ScoreExplanation({ contributions }: { contributions: Contribution[] | null }) {
  if (!contributions || contributions.length === 0) {
    return <p className="muted">No scoring factors recorded yet.</p>;
  }
  const groups = new Map<string, Contribution[]>();
  for (const c of contributions) {
    groups.set(c.component, [...(groups.get(c.component) ?? []), c]);
  }
  const components = [...groups.keys()].sort(
    (a, b) => (ORDER.indexOf(a) + 1 || 99) - (ORDER.indexOf(b) + 1 || 99),
  );
  return (
    <div className="explanation">
      {components.map((component) => (
        <section key={component} aria-label={`${humanize(component)} factors`}>
          <h4>{humanize(component)}</h4>
          <ul className="factor-list">
            {[...(groups.get(component) ?? [])]
              .sort((a, b) => b.points - a.points)
              .map((c, i) => (
                <li key={`${c.factor}-${i}`} className="factor">
                  <span className={`points ${c.points >= 0 ? "points-pos" : "points-neg"}`}>
                    {formatPoints(c.points)}
                  </span>
                  <span>{c.detail}</span>
                </li>
              ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
