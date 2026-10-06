import { useState } from "react";

import { ApiError } from "../api/client";
import type { AccountBrief } from "../api/types";
import { useApp, useCan } from "../app/context";
import { formatDate } from "../lib/format";
import { ErrorNotice } from "./Status";

function List({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) {
    return null;
  }
  return (
    <section>
      <h4>{title}</h4>
      <ul>
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

/** The AI account brief (Claude on Bedrock), generated on demand and cached server-side. */
export function BriefPanel({ leadId, initial }: { leadId: string; initial: AccountBrief | null }) {
  const { api } = useApp();
  const can = useCan();
  const [brief, setBrief] = useState<AccountBrief | null>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function generate() {
    setBusy(true);
    setError(null);
    try {
      setBrief(await api.generateBrief(leadId));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const disabled = error instanceof ApiError && error.code === "brief_unavailable";
  return (
    <div className="brief">
      {brief ? (
        <>
          <p className="brief-summary">{brief.summary}</p>
          <List title="Why now" items={brief.why_now} />
          <List title="Talking points" items={brief.talking_points} />
          <List title="Risks" items={brief.risks} />
          <section>
            <h4>Next step</h4>
            <p>{brief.recommended_next_step}</p>
          </section>
          <p className="muted small">
            Confidence: {brief.confidence} {"·"} {brief.model}
            {brief.generated_at ? ` · ${formatDate(brief.generated_at)}` : ""}
            {" · "}AI-generated from the signals above; verify before use.
          </p>
        </>
      ) : (
        <p className="muted">No brief yet.</p>
      )}
      {disabled ? (
        <p className="muted small">AI briefs are turned off in this environment.</p>
      ) : error ? (
        <ErrorNotice error={error} />
      ) : null}
      {can("ai:brief") && !disabled ? (
        <button type="button" className="button" onClick={generate} disabled={busy}>
          {busy ? "Writing brief…" : brief ? "Refresh brief" : "Generate brief"}
        </button>
      ) : null}
    </div>
  );
}
