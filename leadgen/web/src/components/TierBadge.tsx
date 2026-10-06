import type { Tier } from "../api/types";

const MEANING: Record<Tier, string> = {
  A: "Tier A: strong fit and active intent - work now",
  B: "Tier B: good fit or rising intent - work this week",
  C: "Tier C: partial fit - nurture",
  D: "Tier D: weak fit - monitor only",
};

export function TierBadge({ tier }: { tier: Tier | null }) {
  if (!tier) {
    return <span className="tier tier-none">{"—"}</span>;
  }
  return (
    <span className={`tier tier-${tier.toLowerCase()}`} title={MEANING[tier]}>
      {tier}
    </span>
  );
}

export function HotBadge({ hot }: { hot: boolean }) {
  return hot ? (
    <span className="badge badge-hot" title="Fresh high-intent activity">
      Hot
    </span>
  ) : null;
}
