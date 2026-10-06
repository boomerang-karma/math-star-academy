/** Display formatting shared by the pages. Pure functions, unit-tested. */

export const EMPTY = "—";

const SOURCE_LABELS: Record<string, string> = {
  "scrapebadger.linkedin.company": "LinkedIn company page (ScrapeBadger)",
  "scrapebadger.linkedin.profile": "LinkedIn profile (ScrapeBadger)",
  "scrapebadger.linkedin.jobs": "LinkedIn jobs (ScrapeBadger)",
  "scrapebadger.google.maps": "Google Maps (ScrapeBadger)",
  "scrapebadger.google.serp": "Google Search (ScrapeBadger)",
  "scrapebadger.google.news": "Google News (ScrapeBadger)",
  "scrapebadger.web": "Company website (ScrapeBadger)",
  "linkedin.lead_sync": "LinkedIn Lead Gen Forms",
  "google.ga4": "Google Analytics 4",
  "first_party.web": "Our website",
  crm: "CRM",
  manual: "Manual entry",
};

const SIGNAL_LABELS: Record<string, string> = {
  job_posting: "Job posting",
  funding: "Funding",
  acquisition: "Acquisition",
  expansion: "Expansion",
  leadership_change: "Leadership change",
  news_mention: "News mention",
  tech_detected: "Technology detected",
  web_visit: "Website visit",
  high_intent_page: "High-intent page view",
  content_download: "Content download",
  form_submission: "Form submission",
  email_click: "Email click",
  meeting_booked: "Meeting booked",
};

const WORDS: Record<string, string> = {
  hq: "HQ",
  url: "URL",
  linkedin: "LinkedIn",
  ga4: "GA4",
  crm: "CRM",
  ai: "AI",
  id: "ID",
};

export function humanize(value: string): string {
  const words = value
    .replace(/[_.]+/g, " ")
    .trim()
    .split(/\s+/)
    .map((word) => WORDS[word.toLowerCase()] ?? word);
  const text = words.join(" ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function sourceLabel(source: string | null | undefined): string {
  if (!source) {
    return EMPTY;
  }
  return SOURCE_LABELS[source] ?? humanize(source);
}

export function signalLabel(type: string): string {
  return SIGNAL_LABELS[type] ?? humanize(type);
}

export function formatScore(score: number | null | undefined): string {
  return score === null || score === undefined || Number.isNaN(score) ? EMPTY : score.toFixed(1);
}

export function formatPoints(points: number): string {
  const rounded = Math.round(points * 10) / 10;
  return `${rounded > 0 ? "+" : ""}${rounded.toFixed(1)}`;
}

export function formatPercent(probability: number): string {
  return `${(probability * 100).toFixed(1)}%`;
}

export function formatCount(value: number | null | undefined): string {
  return value === null || value === undefined ? EMPTY : new Intl.NumberFormat("en-US").format(value);
}

const DATE_FORMAT = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

export function formatDate(iso: string | null | undefined): string {
  if (!iso) {
    return EMPTY;
  }
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? EMPTY : DATE_FORMAT.format(date);
}

const RELATIVE = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 24 * 3600],
  ["month", 30 * 24 * 3600],
  ["week", 7 * 24 * 3600],
  ["day", 24 * 3600],
  ["hour", 3600],
  ["minute", 60],
];

export function relativeTime(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) {
    return EMPTY;
  }
  const at = new Date(iso).getTime();
  if (Number.isNaN(at)) {
    return EMPTY;
  }
  const seconds = (at - now) / 1000;
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) {
      return RELATIVE.format(Math.round(seconds / size), unit);
    }
  }
  return "just now";
}

/** Render an attribute value from a golden record. */
export function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return EMPTY;
  }
  if (Array.isArray(value)) {
    return value.length ? value.map((v) => formatValue(v)).join(", ") : EMPTY;
  }
  if (typeof value === "number") {
    return Number.isInteger(value) ? formatCount(value) : String(value);
  }
  if (typeof value === "boolean") {
    return value ? "Yes" : "No";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

/** Only http(s) links are rendered as anchors; anything else (javascript:, data:) is text. */
export function safeHref(url: string | null | undefined): string | null {
  if (!url) {
    return null;
  }
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
  } catch {
    return null;
  }
}
