import { useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../api/client";
import type { TrackedCompany, TrackedCompanyInput } from "../api/types";
import { useApp, useCan, useResource } from "../app/context";
import { ErrorNotice, Loading } from "../components/Status";
import { TierBadge } from "../components/TierBadge";
import { formatScore, humanize, relativeTime } from "../lib/format";

const EMPTY_FORM = { name: "", domain: "", linkedin: "", notes: "" };

function AddCompanyForm({ onAdded }: { onAdded: (company: TrackedCompany) => void }) {
  const { api } = useApp();
  const [form, setForm] = useState(EMPTY_FORM);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  function set(field: keyof typeof EMPTY_FORM, value: string) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const input: TrackedCompanyInput = { name: form.name.trim() };
    if (form.domain.trim()) input.domain = form.domain.trim();
    if (form.linkedin.trim()) input.linkedin = form.linkedin.trim();
    if (form.notes.trim()) input.notes = form.notes.trim();
    setBusy(true);
    setError(null);
    try {
      onAdded(await api.addTrackedCompany(input));
      setForm(EMPTY_FORM);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card tracked-form" onSubmit={(e) => void submit(e)} aria-labelledby="add-h">
      <h2 id="add-h">Add a company</h2>
      <div className="form-grid">
        <label>
          Company name
          <input
            required
            maxLength={200}
            value={form.name}
            onChange={(e) => set("name", e.target.value)}
            placeholder="Northwind Analytics"
          />
        </label>
        <label>
          Website domain <span className="muted small">(recommended)</span>
          <input
            maxLength={253}
            value={form.domain}
            onChange={(e) => set("domain", e.target.value)}
            placeholder="northwindanalytics.com"
          />
        </label>
        <label>
          LinkedIn company page <span className="muted small">(optional)</span>
          <input
            maxLength={300}
            value={form.linkedin}
            onChange={(e) => set("linkedin", e.target.value)}
            placeholder="linkedin.com/company/northwind-analytics"
          />
        </label>
        <label>
          Notes <span className="muted small">(optional)</span>
          <input
            maxLength={1000}
            value={form.notes}
            onChange={(e) => set("notes", e.target.value)}
            placeholder="Why we're tracking them"
          />
        </label>
      </div>
      <p className="muted small">
        A domain or LinkedIn page makes matching exact. With only a name, research first looks the
        company up on Google.
      </p>
      {error ? <ErrorNotice error={error} /> : null}
      <button type="submit" className="button button-primary" disabled={busy || !form.name.trim()}>
        {busy ? "Adding…" : "Add company"}
      </button>
    </form>
  );
}

function researchMessage(error: unknown): string {
  if (error instanceof ApiError && error.code === "enrichment_unavailable") {
    return "Research runs on the AWS pipeline, so it isn't available in this local copy.";
  }
  return error instanceof Error ? error.message : String(error);
}

function CompanyRow({
  company,
  onChange,
  onRemove,
}: {
  company: TrackedCompany;
  onChange: (company: TrackedCompany) => void;
  onRemove: (id: string) => void;
}) {
  const { api } = useApp();
  const can = useCan();
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function act(name: string, run: () => Promise<void>) {
    setBusy(name);
    setMessage(null);
    try {
      await run();
    } catch (err) {
      setMessage(name === "research" ? researchMessage(err) : err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  const paused = company.status === "paused";
  return (
    <tr className={paused ? "row-paused" : undefined}>
      <td>
        <span className="strong">{company.name}</span>
        <div className="muted small">
          {[company.domain, company.linkedin_slug ? `linkedin.com/company/${company.linkedin_slug}` : null]
            .filter(Boolean)
            .join(" · ") || "Name only"}
        </div>
        {company.notes ? <div className="small">{company.notes}</div> : null}
      </td>
      <td>
        <span className={`badge ${paused ? "" : "badge-active"}`}>{humanize(company.status)}</span>
      </td>
      <td>
        {company.entity ? (
          <>
            <Link to={company.lead ? `/leads/${company.lead.id}` : `/entities/${company.entity.id}`}>
              {company.entity.name ?? "Open record"}
            </Link>
            {company.lead ? (
              <div className="small">
                <TierBadge tier={company.lead.tier} /> {formatScore(company.lead.score)}
              </div>
            ) : (
              <div className="muted small">Not scored yet</div>
            )}
          </>
        ) : (
          <span className="muted small">Not in the graph yet</span>
        )}
      </td>
      <td>
        {company.last_research_at ? (
          <>
            {relativeTime(company.last_research_at)}
            <div className="muted small">{company.last_run_status ? humanize(company.last_run_status) : ""}</div>
          </>
        ) : (
          <span className="muted small">Never</span>
        )}
      </td>
      <td>
        <div className="row-actions">
          {can("connectors:run") ? (
            <button
              type="button"
              className="button"
              disabled={busy !== null || paused}
              title={paused ? "Resume tracking to research this company" : undefined}
              onClick={() =>
                void act("research", async () => {
                  await api.researchTrackedCompany(company.id);
                  onChange({ ...company, last_research_at: new Date().toISOString(), last_run_status: "queued" });
                })
              }
            >
              {busy === "research" ? "Starting…" : "Research now"}
            </button>
          ) : null}
          <button
            type="button"
            className="button"
            disabled={busy !== null}
            onClick={() =>
              void act("status", async () =>
                onChange(await api.updateTrackedCompany(company.id, { status: paused ? "active" : "paused" })),
              )
            }
          >
            {paused ? "Resume" : "Pause"}
          </button>
          <button
            type="button"
            className="button button-quiet"
            disabled={busy !== null}
            onClick={() => {
              if (window.confirm(`Stop tracking ${company.name}? Data already collected stays.`)) {
                void act("remove", async () => {
                  await api.removeTrackedCompany(company.id);
                  onRemove(company.id);
                });
              }
            }}
          >
            Remove
          </button>
        </div>
        {message ? (
          <p className="small notice-inline" role="alert">
            {message}
          </p>
        ) : null}
      </td>
    </tr>
  );
}

/** Admin: the companies we deliberately add and follow, researched daily while active. */
export function TrackedCompanies() {
  const { api } = useApp();
  const list = useResource(() => api.trackedCompanies(), [api]);
  const [items, setItems] = useState<TrackedCompany[] | null>(null);
  const companies = items ?? list.data?.items ?? [];

  function upsert(company: TrackedCompany) {
    setItems(() => {
      const current = items ?? list.data?.items ?? [];
      const exists = current.some((c) => c.id === company.id);
      return exists ? current.map((c) => (c.id === company.id ? company : c)) : [company, ...current];
    });
  }

  function remove(id: string) {
    setItems((items ?? list.data?.items ?? []).filter((c) => c.id !== id));
  }

  const active = companies.filter((c) => c.status === "active").length;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Tracked companies</h1>
          <p className="muted">
            Companies you choose to follow. Active ones are researched every day (LinkedIn page, website and
            news) and appear in the leads list once found.
          </p>
        </div>
      </div>

      <AddCompanyForm onAdded={upsert} />

      {list.loading ? (
        <Loading />
      ) : list.error ? (
        <ErrorNotice error={list.error} onRetry={list.reload} />
      ) : companies.length === 0 ? (
        <p className="empty">No tracked companies yet. Add the first one above.</p>
      ) : (
        <div className="table-wrap tracked-table">
          <table className="table">
            <caption>
              {active} active · {companies.length - active} paused
            </caption>
            <thead>
              <tr>
                <th scope="col">Company</th>
                <th scope="col">Status</th>
                <th scope="col">In LeadIntel</th>
                <th scope="col">Last research</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {companies.map((company) => (
                <CompanyRow key={company.id} company={company} onChange={upsert} onRemove={remove} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
