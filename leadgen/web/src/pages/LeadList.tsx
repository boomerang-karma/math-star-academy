import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import type { LeadFilters } from "../api/client";
import type { LeadStatus, LeadSummary, Tier } from "../api/types";
import { LEAD_STATUSES } from "../api/types";
import { useApp, useResource } from "../app/context";
import { ScoreBar } from "../components/ScoreBar";
import { ErrorNotice, Loading } from "../components/Status";
import { HotBadge, TierBadge } from "../components/TierBadge";
import { EMPTY, formatCount, formatScore, humanize, relativeTime } from "../lib/format";

const TIERS: Tier[] = ["A", "B", "C", "D"];

function filtersFrom(params: URLSearchParams): LeadFilters {
  const tier = params.get("tier");
  const status = params.get("status");
  return {
    tier: TIERS.includes(tier as Tier) ? (tier as Tier) : undefined,
    status: LEAD_STATUSES.includes(status as LeadStatus) ? (status as LeadStatus) : undefined,
    hot: params.get("hot") === "true" ? true : undefined,
    q: params.get("q") ?? undefined,
  };
}

export function LeadList() {
  const { api, me } = useApp();
  const [params, setParams] = useSearchParams();
  const filters = filtersFrom(params);
  const key = params.toString();
  const first = useResource(() => api.leads({ ...filters, limit: 50 }), [api, key, me?.subject]);
  const [extra, setExtra] = useState<LeadSummary[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [moreError, setMoreError] = useState<unknown>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  useEffect(() => {
    setExtra([]);
    setCursor(first.data?.next_cursor ?? null);
  }, [first.data]);

  function update(name: string, value: string | null) {
    const next = new URLSearchParams(params);
    if (value) {
      next.set(name, value);
    } else {
      next.delete(name);
    }
    setParams(next, { replace: true });
  }

  async function loadMore() {
    if (!cursor) {
      return;
    }
    setLoadingMore(true);
    setMoreError(null);
    try {
      const page = await api.leads({ ...filters, limit: 50, cursor });
      setExtra((items) => [...items, ...page.items]);
      setCursor(page.next_cursor);
    } catch (err) {
      setMoreError(err);
    } finally {
      setLoadingMore(false);
    }
  }

  const items = [...(first.data?.items ?? []), ...extra];
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Leads</h1>
          <p className="muted">
            Ranked by score. {me?.row_scope === "territory" ? "Showing your territories and assigned leads." : ""}
          </p>
        </div>
      </div>

      <form className="filters" onSubmit={(e) => e.preventDefault()} aria-label="Filter leads">
        <label>
          Tier
          <select value={filters.tier ?? ""} onChange={(e) => update("tier", e.target.value || null)}>
            <option value="">All</option>
            {TIERS.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <label>
          Status
          <select value={filters.status ?? ""} onChange={(e) => update("status", e.target.value || null)}>
            <option value="">All</option>
            {LEAD_STATUSES.map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </select>
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={filters.hot === true}
            onChange={(e) => update("hot", e.target.checked ? "true" : null)}
          />
          Hot only
        </label>
        <label className="grow">
          Company
          <input
            key={filters.q ?? ""}
            type="search"
            defaultValue={filters.q ?? ""}
            placeholder="Name or domain"
            maxLength={100}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                update("q", e.currentTarget.value.trim() || null);
              }
            }}
          />
        </label>
      </form>

      {first.loading ? (
        <Loading />
      ) : first.error ? (
        <ErrorNotice error={first.error} onRetry={first.reload} />
      ) : items.length === 0 ? (
        <p className="empty">No leads match these filters.</p>
      ) : (
        <div className="table-wrap">
          <table className="table leads">
            <thead>
              <tr>
                <th scope="col">Tier</th>
                <th scope="col">Account</th>
                <th scope="col">Contact</th>
                <th scope="col" className="col-score">
                  Score
                </th>
                <th scope="col">Fit / Intent / Engagement</th>
                <th scope="col">Last signal</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {items.map((lead) => (
                <tr key={lead.id}>
                  <td>
                    <TierBadge tier={lead.tier} />
                  </td>
                  <td>
                    <Link to={`/leads/${lead.id}`} className="strong">
                      {lead.organization.name ?? lead.organization.domain ?? "Unknown account"}
                    </Link>{" "}
                    <HotBadge hot={lead.hot} />
                    <div className="muted small">
                      {[
                        lead.organization.domain,
                        lead.organization.industry,
                        lead.organization.country,
                        lead.organization.employees ? `${formatCount(lead.organization.employees)} staff` : null,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </div>
                  </td>
                  <td>
                    {lead.person ? (
                      <>
                        {lead.person.name ?? EMPTY}
                        <div className="muted small">{lead.person.title ?? ""}</div>
                      </>
                    ) : (
                      <span className="muted">Account-level</span>
                    )}
                  </td>
                  <td className="col-score">
                    <ScoreBar label="Score" value={lead.score} compact />
                  </td>
                  <td className="mono">
                    {formatScore(lead.fit)} / {formatScore(lead.intent)} / {formatScore(lead.engagement)}
                  </td>
                  <td>{relativeTime(lead.last_signal_at)}</td>
                  <td>{humanize(lead.status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {moreError ? <ErrorNotice error={moreError} /> : null}
      {cursor && !first.loading ? (
        <button type="button" className="button" onClick={loadMore} disabled={loadingMore}>
          {loadingMore ? "Loading…" : "Load more"}
        </button>
      ) : null}
    </>
  );
}
