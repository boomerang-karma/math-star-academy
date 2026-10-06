import type { AttributeView } from "../api/types";
import { formatDate, formatValue, humanize, sourceLabel } from "../lib/format";

/**
 * The golden record, one row per attribute: the surviving value, where it came
 * from and when, how many sources agree, and the values that lost.
 */
export function ProvenanceTable({
  attributes,
  caption,
}: {
  attributes: Record<string, AttributeView>;
  caption: string;
}) {
  const names = Object.keys(attributes).sort();
  if (names.length === 0) {
    return <p className="muted">No attributes yet.</p>;
  }
  return (
    <div className="table-wrap">
      <table className="table provenance">
        <caption>{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Attribute</th>
            <th scope="col">Value</th>
            <th scope="col">Source</th>
            <th scope="col">Observed</th>
            <th scope="col">Agreeing sources</th>
          </tr>
        </thead>
        <tbody>
          {names.map((name) => {
            const attr = attributes[name] as AttributeView;
            return (
              <tr key={name}>
                <th scope="row">{humanize(name)}</th>
                <td>
                  <span className="value">{formatValue(attr.value)}</span>
                  {attr.alternatives.length > 0 ? (
                    <details className="alternatives">
                      <summary>
                        {attr.alternatives.length} other value{attr.alternatives.length === 1 ? "" : "s"}
                      </summary>
                      <ul>
                        {attr.alternatives.map((alt, i) => (
                          <li key={i}>
                            {formatValue(alt.value)}{" "}
                            <span className="muted small">
                              {sourceLabel(alt.source)}, {formatDate(alt.observed_at)}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </details>
                  ) : null}
                </td>
                <td>{sourceLabel(attr.source)}</td>
                <td>{formatDate(attr.observed_at)}</td>
                <td>{attr.agreeing_sources}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
