import { describe, expect, it } from "vitest";

import {
  EMPTY,
  formatDate,
  formatPercent,
  formatPoints,
  formatScore,
  formatValue,
  humanize,
  relativeTime,
  safeHref,
  signalLabel,
  sourceLabel,
} from "./format";

describe("format", () => {
  it("labels sources and signals, falling back to a readable form", () => {
    expect(sourceLabel("scrapebadger.linkedin.company")).toBe("LinkedIn company page (ScrapeBadger)");
    expect(sourceLabel("google.ga4")).toBe("Google Analytics 4");
    expect(sourceLabel("partner.feed")).toBe("Partner feed");
    expect(sourceLabel(null)).toBe(EMPTY);
    expect(signalLabel("high_intent_page")).toBe("High-intent page view");
    expect(humanize("employee_count")).toBe("Employee count");
    expect(humanize("hq_country")).toBe("HQ country");
    expect(humanize("linkedin_url")).toBe("LinkedIn URL");
  });

  it("formats numbers", () => {
    expect(formatScore(81.714)).toBe("81.7");
    expect(formatScore(null)).toBe(EMPTY);
    expect(formatPoints(12.34)).toBe("+12.3");
    expect(formatPoints(-4)).toBe("-4.0");
    expect(formatPercent(0.8808)).toBe("88.1%");
  });

  it("formats dates in UTC and relative to now", () => {
    expect(formatDate("2026-09-12T23:30:00Z")).toMatch(/^12 Sept? 2026$/); // ICU versions differ
    expect(formatDate("not a date")).toBe(EMPTY);
    const now = Date.parse("2026-10-06T12:00:00Z");
    expect(relativeTime("2026-10-03T12:00:00Z", now)).toBe("3 days ago");
    expect(relativeTime("2026-10-06T11:59:30Z", now)).toBe("just now");
    expect(relativeTime("2026-10-06T14:00:00Z", now)).toBe("in 2 hours");
    expect(relativeTime(null, now)).toBe(EMPTY);
  });

  it("renders golden-record values", () => {
    expect(formatValue(["python", "aws"])).toBe("python, aws");
    expect(formatValue(1200)).toBe("1,200");
    expect(formatValue(true)).toBe("Yes");
    expect(formatValue("")).toBe(EMPTY);
    expect(formatValue({ a: 1 })).toBe('{"a":1}');
  });

  it("only links http(s) URLs", () => {
    expect(safeHref("https://example.com/news")).toBe("https://example.com/news");
    expect(safeHref("javascript:alert(1)")).toBeNull();
    expect(safeHref("data:text/html,hi")).toBeNull();
    expect(safeHref("/relative")).toBeNull();
    expect(safeHref(null)).toBeNull();
  });
});
