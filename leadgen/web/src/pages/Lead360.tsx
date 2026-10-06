import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import type { Lead360 as Lead360Data, LeadStatus } from "../api/types";
import { LEAD_STATUSES } from "../api/types";
import { useApp, useCan, useResource } from "../app/context";
import { BriefPanel } from "../components/BriefPanel";
import { GraphView } from "../components/GraphView";
import { ProvenanceTable } from "../components/ProvenanceTable";
import { ScoreBar, Sparkline } from "../components/ScoreBar";
import { ScoreExplanation } from "../components/ScoreExplanation";
import { SignalTimeline } from "../components/SignalTimeline";
import { ErrorNotice, Loading } from "../components/Status";
import { HotBadge, TierBadge } from "../components/TierBadge";
import { EMPTY, formatDate, formatScore, formatValue, humanize, sourceLabel } from "../lib/format";

function StatusControl({ lead }: { lead: Lead360Data["lead"] }) {
  const { api } = useApp();
  const can = useCan();
  const [status, setStatus] = useState<LeadStatus>(lead.status);
  const [error, setError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);

  if (!can("leads:write")) {
    return <span className="badge">{humanize(status)}</span>;
  }
  async function change(next: LeadStatus) {
    const previous = status;
    setStatus(next);
    setSaving(true);
    setError(null);
    try {
      await api.updateLead(lead.id, { status: next });
    } catch (err) {
      setStatus(previous);
      setError(err);
    } finally {
      setSaving(false);
    }
  }
  return (
    <div className="status-control">
      <label>
        Status{" "}
        <select value={status} disabled={saving} onChange={(e) => void change(e.target.value as LeadStatus)}>
          {LEAD_STATUSES.map((s) => (
            <option key={s} value={s}>
              {humanize(s)}
            </option>
          ))}
        </select>
      </label>
      {saving ? (
        <span className="muted small" role="status">
          Saving{"…"}
        </span>
      ) : null}
      {error ? <ErrorNotice error={error} /> : null}
    </div>
  );
}

function ContactCard({ data }: { data: Lead360Data }) {
  const person = data.person;
  if (!person) {
    return <p className="muted">No contact identified yet; this is an account-level lead.</p>;
  }
  const title = person.attributes["title"]?.value;
  const contact = person.contact;
  return (
    <div className="contact">
      <p>
        <Link to={`/entities/${person.id}`} className="strong">
          {person.display_name ?? "Unnamed contact"}
        </Link>
        <br />
        <span className="muted">{formatValue(title)}</span>
      </p>
      {data.suppressed ? (
        <div className="notice notice-warn" role="note">
          <strong>Do not contact.</strong> This person is on the suppression list.
        </div>
      ) : null}
      <dl className="facts">
        <dt>Email</dt>
        <dd className="mono">{contact?.email ?? EMPTY}</dd>
        <dt>Phone</dt>
        <dd className="mono">{contact?.phone ?? EMPTY}</dd>
      </dl>
      {contact?.masked ? (
        <p className="muted small">Contact details are masked for your role.</p>
      ) : contact ? (
        <p className="muted small">Viewing contact details is recorded in the audit log.</p>
      ) : null}
      <h4>Consent</h4>
      {data.consent.length === 0 ? (
        <p className="muted small">No consent records. Outreach relies on legitimate interest; check the playbook.</p>
      ) : (
        <ul className="consent">
          {data.consent.map((c) => (
            <li key={`${c.purpose}-${c.captured_at}`}>
              <span className={`badge badge-consent-${c.status}`}>{humanize(c.status)}</span> {humanize(c.purpose)}{" "}
              <span className="muted small">
                {sourceLabel(c.source)}, {formatDate(c.captured_at)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Lead360() {
  const { id = "" } = useParams();
  const { api } = useApp();
  const { data, error, loading, reload } = useResource(() => api.lead(id), [api, id]);

  if (loading) {
    return <Loading />;
  }
  if (error || !data) {
    return <ErrorNotice error={error} onRetry={reload} />;
  }
  const { lead, organization } = data;
  const focus = [organization?.id, data.person?.id].filter((v): v is string => Boolean(v));
  const name = organization?.display_name ?? organization?.domain ?? "Unknown account";
  return (
    <>
      <p className="crumbs">
        <Link to="/leads">Leads</Link> / {name}
      </p>
      <div className="page-head">
        <div>
          <h1>
            {name} <TierBadge tier={lead.tier} /> <HotBadge hot={lead.hot} />
          </h1>
          <p className="muted">
            {[
              organization?.domain,
              formatValue(organization?.attributes["industry"]?.value),
              lead.owner ? `Owner: ${lead.owner.name ?? lead.owner.id}` : "Unassigned",
              lead.scored_at ? `Scored ${formatDate(lead.scored_at)}` : null,
            ]
              .filter((v) => v && v !== EMPTY)
              .join(" · ")}
          </p>
        </div>
        <StatusControl lead={lead} />
      </div>

      <div className="grid">
        <section className="card" aria-labelledby="score-h">
          <h2 id="score-h">
            Score <span className="score-total">{formatScore(lead.score)}</span>
          </h2>
          <ScoreBar label="Fit" value={lead.components.fit} />
          <ScoreBar label="Intent" value={lead.components.intent} />
          <ScoreBar label="Engagement" value={lead.components.engagement} />
          <Sparkline points={lead.history} />
          <h3>Why this score</h3>
          <ScoreExplanation contributions={lead.explanation} />
        </section>

        <section className="card" aria-labelledby="contact-h">
          <h2 id="contact-h">Contact</h2>
          <ContactCard data={data} />
        </section>

        <section className="card" aria-labelledby="brief-h">
          <h2 id="brief-h">Account brief</h2>
          <BriefPanel leadId={lead.id} initial={data.brief} />
        </section>

        <section className="card" aria-labelledby="signals-h">
          <h2 id="signals-h">Signals</h2>
          <SignalTimeline signals={data.signals} />
        </section>

        <section className="card span-2" aria-labelledby="graph-h">
          <h2 id="graph-h">Relationships</h2>
          <GraphView graph={data.graph} focusIds={focus} />
        </section>

        {organization ? (
          <section className="card span-2" aria-labelledby="org-h">
            <h2 id="org-h">
              Company record{" "}
              <Link to={`/entities/${organization.id}`} className="small">
                lineage
              </Link>
            </h2>
            <ProvenanceTable attributes={organization.attributes} caption={`Golden record for ${name}`} />
          </section>
        ) : null}

        {data.person ? (
          <section className="card span-2" aria-labelledby="person-h">
            <h2 id="person-h">
              Person record{" "}
              <Link to={`/entities/${data.person.id}`} className="small">
                lineage
              </Link>
            </h2>
            <ProvenanceTable
              attributes={data.person.attributes}
              caption={`Golden record for ${data.person.display_name ?? "contact"}`}
            />
          </section>
        ) : null}
      </div>
    </>
  );
}
