import { Link, useSearchParams } from "react-router-dom";

import { useApp, useResource } from "../app/context";
import { ErrorNotice, Loading } from "../components/Status";
import { EMPTY, humanize } from "../lib/format";

export function SearchPage() {
  const { api } = useApp();
  const [params] = useSearchParams();
  const q = (params.get("q") ?? "").trim();
  const results = useResource(
    () => (q.length >= 2 ? api.search(q) : Promise.resolve({ items: [] })),
    [api, q],
  );
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Search</h1>
          <p className="muted">{q ? `Companies and people matching “${q}”` : "Type at least two characters."}</p>
        </div>
      </div>
      {results.loading ? (
        <Loading />
      ) : results.error ? (
        <ErrorNotice error={results.error} onRetry={results.reload} />
      ) : results.data && results.data.items.length > 0 ? (
        <ul className="results">
          {results.data.items.map((hit) => (
            <li key={hit.id}>
              <span className={`badge badge-${hit.type}`}>{humanize(hit.type)}</span>{" "}
              <Link to={`/entities/${hit.id}`} className="strong">
                {hit.name ?? hit.domain ?? hit.id.slice(0, 8)}
              </Link>{" "}
              <span className="muted small">{hit.domain ?? EMPTY}</span>
            </li>
          ))}
        </ul>
      ) : q ? (
        <p className="empty">No matches.</p>
      ) : null}
    </>
  );
}
