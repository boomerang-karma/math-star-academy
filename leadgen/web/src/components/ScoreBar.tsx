import { formatScore } from "../lib/format";

/** A 0-100 bar drawn with SVG attributes (no inline styles, so it works under a strict CSP). */
export function ScoreBar({
  label,
  value,
  compact = false,
}: {
  label: string;
  value: number | null;
  compact?: boolean;
}) {
  const clamped = Math.max(0, Math.min(100, value ?? 0));
  const band = clamped >= 70 ? "high" : clamped >= 40 ? "mid" : "low";
  return (
    <div className={compact ? "scorebar scorebar-compact" : "scorebar"}>
      <span className={compact ? "visually-hidden" : "scorebar-label"}>{label}</span>
      <svg
        className="scorebar-track"
        viewBox="0 0 100 8"
        preserveAspectRatio="none"
        role="img"
        aria-label={`${label}: ${formatScore(value)} of 100`}
      >
        <rect className="scorebar-bg" x="0" y="0" width="100" height="8" rx="4" />
        <rect className={`scorebar-fill scorebar-${band}`} x="0" y="0" width={clamped} height="8" rx="4" />
      </svg>
      <span className="scorebar-value">{formatScore(value)}</span>
    </div>
  );
}

/** Score history as a small line chart. */
export function Sparkline({ points }: { points: { at: string; score: number }[] }) {
  if (points.length < 2) {
    return null;
  }
  const ordered = [...points].sort((a, b) => a.at.localeCompare(b.at));
  const step = 100 / (ordered.length - 1);
  const path = ordered
    .map((p, i) => `${i === 0 ? "M" : "L"}${(i * step).toFixed(1)},${(30 - (p.score / 100) * 28 - 1).toFixed(1)}`)
    .join(" ");
  const first = ordered[0]?.score ?? 0;
  const last = ordered[ordered.length - 1]?.score ?? 0;
  return (
    <svg
      className="sparkline"
      viewBox="0 0 100 30"
      preserveAspectRatio="none"
      role="img"
      aria-label={`Score history: ${formatScore(first)} to ${formatScore(last)} over ${ordered.length} scoring runs`}
    >
      <path d={path} />
    </svg>
  );
}
