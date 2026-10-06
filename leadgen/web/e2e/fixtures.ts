/** API fixtures for the end-to-end suite (fictional companies and people). */

export const LEAD_ID = "11111111-1111-4111-8111-111111111111";
export const ORG_ID = "22222222-2222-4222-8222-222222222222";
export const PERSON_ID = "33333333-3333-4333-8333-333333333333";
export const PARENT_ID = "44444444-4444-4444-8444-444444444444";
export const REVIEW_ID = "55555555-5555-4555-8555-555555555555";

const ALL_PERMISSIONS = [
  "ai:brief",
  "audit:read",
  "compliance:dsar",
  "compliance:suppress",
  "connectors:configure",
  "connectors:run",
  "entities:merge",
  "entities:read",
  "leads:assign",
  "leads:read",
  "leads:write",
  "pii:read",
  "users:admin",
];

export function me(roles: string[]) {
  const viewer = roles.includes("viewer");
  return {
    subject: "00000000-0000-4000-8000-000000000001",
    roles,
    permissions: viewer ? ["entities:read", "leads:read"] : ALL_PERMISSIONS,
    territories: [],
    row_scope: "global",
  };
}

export const leads = {
  items: [
    {
      id: LEAD_ID,
      status: "new",
      tier: "A",
      score: 81.71,
      fit: 88,
      intent: 74.2,
      engagement: 61,
      hot: true,
      scored_at: "2026-10-05T08:00:00Z",
      organization: {
        id: ORG_ID,
        name: "Northwind Analytics",
        domain: "northwind-analytics.example",
        industry: "Software Development",
        country: "GB",
        employees: 420,
      },
      person: { id: PERSON_ID, name: "Jordan Lee", title: "VP Data Platform" },
      last_signal_at: "2026-10-04T10:00:00Z",
    },
    {
      id: "66666666-6666-4666-8666-666666666666",
      status: "nurture",
      tier: "B",
      score: 58.2,
      fit: 70,
      intent: 30,
      engagement: 12,
      hot: false,
      scored_at: "2026-10-05T08:00:00Z",
      organization: {
        id: "77777777-7777-4777-8777-777777777777",
        name: "Contoso Freight",
        domain: "contoso-freight.example",
        industry: "Logistics",
        country: "US",
        employees: 1800,
      },
      person: null,
      last_signal_at: "2026-09-20T10:00:00Z",
    },
  ],
  next_cursor: null,
};

const attribute = (value: unknown, source: string, extra: Record<string, unknown> = {}) => ({
  value,
  source,
  observed_at: "2026-10-01T00:00:00Z",
  record_id: "88888888-8888-4888-8888-888888888888",
  confidence: 0.9,
  agreeing_sources: 1,
  alternatives: [],
  ...extra,
});

export const lead360 = {
  lead: {
    id: LEAD_ID,
    status: "new",
    tier: "A",
    score: 81.71,
    components: { fit: 88, intent: 74.2, engagement: 61 },
    hot: true,
    explanation: [
      { component: "fit", factor: "industry", points: 25, detail: "Industry matches ICP: Software Development" },
      { component: "fit", factor: "size", points: 20, detail: "420 employees is inside the 200-2,000 sweet spot" },
      { component: "intent", factor: "funding", points: 30.5, detail: "Funding 9 days ago: Raised Series B" },
      { component: "engagement", factor: "high_intent_page", points: 18, detail: "Visited /pricing 2 days ago" },
    ],
    scored_at: "2026-10-05T08:00:00Z",
    territory: "EMEA",
    owner: null,
    history: [
      { at: "2026-09-20T08:00:00Z", score: 55, tier: "B" },
      { at: "2026-10-05T08:00:00Z", score: 81.71, tier: "A" },
    ],
  },
  organization: {
    id: ORG_ID,
    type: "organization",
    display_name: "Northwind Analytics",
    status: "active",
    merged_into: null,
    domain: "northwind-analytics.example",
    attributes: {
      industry: attribute("Software Development", "scrapebadger.linkedin.company", {
        agreeing_sources: 2,
        alternatives: [{ value: "IT Services", source: "scrapebadger.google.maps", observed_at: "2026-08-01T00:00:00Z" }],
      }),
      employee_count: attribute(420, "scrapebadger.linkedin.company"),
      hq_country: attribute("GB", "scrapebadger.google.maps"),
    },
    contact: null,
    updated_at: "2026-10-05T08:00:00Z",
  },
  person: {
    id: PERSON_ID,
    type: "person",
    display_name: "Jordan Lee",
    status: "active",
    merged_into: null,
    domain: null,
    attributes: {
      title: attribute("VP Data Platform", "linkedin.lead_sync"),
      seniority: attribute("vp", "linkedin.lead_sync"),
    },
    contact: { email: "jordan.lee@northwind-analytics.example", phone: "+44 20 7946 0000", masked: false },
    updated_at: "2026-10-05T08:00:00Z",
  },
  signals: [
    {
      id: "99999999-9999-4999-8999-999999999991",
      type: "funding",
      source: "scrapebadger.google.news",
      occurred_at: "2026-09-27T09:00:00Z",
      title: "Northwind Analytics raises Series B",
      url: "https://news.example/northwind-series-b",
      strength: 0.9,
      entity_id: ORG_ID,
    },
    {
      id: "99999999-9999-4999-8999-999999999992",
      type: "high_intent_page",
      source: "first_party.web",
      occurred_at: "2026-10-04T10:00:00Z",
      title: "Viewed /pricing",
      url: "javascript:alert(1)",
      strength: 0.8,
      entity_id: PERSON_ID,
    },
  ],
  graph: {
    nodes: [
      { id: ORG_ID, type: "organization", label: "Northwind Analytics" },
      { id: PERSON_ID, type: "person", label: "Jordan Lee" },
      { id: PARENT_ID, type: "organization", label: "Northwind Group" },
    ],
    edges: [
      {
        id: "e-1",
        source: PERSON_ID,
        target: ORG_ID,
        type: "works_at",
        properties: {},
        provenance: "linkedin.lead_sync",
        confidence: 0.95,
      },
      {
        id: "e-2",
        source: ORG_ID,
        target: PARENT_ID,
        type: "subsidiary_of",
        properties: {},
        provenance: "scrapebadger.web",
        confidence: 0.7,
      },
    ],
  },
  consent: [
    { purpose: "marketing_email", status: "granted", source: "linkedin.lead_sync", captured_at: "2026-10-04T10:05:00Z" },
  ],
  suppressed: false,
  brief: null,
};

export const brief = {
  cached: false,
  model: "anthropic.claude-opus-5-5",
  summary: "Northwind Analytics is a UK data-platform vendor that just raised a Series B.",
  why_now: ["Series B announced 9 days ago (funding signal)"],
  talking_points: ["How they plan to scale the data platform team after the raise"],
  risks: ["No budget owner identified yet"],
  recommended_next_step: "Send Jordan Lee a note referencing the pricing-page visit.",
  confidence: "medium",
};

export const reviews = {
  items: [
    {
      id: REVIEW_ID,
      probability: 0.8808,
      evidence: [
        { feature: "name", weight: 2.1, detail: "names match (similarity 0.97)" },
        { feature: "company", weight: 1.4, detail: "same employer domain" },
        { feature: "location", weight: -0.6, detail: "different cities" },
      ],
      entity_type: "person",
      record_source: "linkedin.lead_sync",
      record_entity: { id: PERSON_ID, name: "Jordan Lee" },
      candidate_entity: { id: "abababab-abab-4bab-8bab-abababababab", name: "Jordan Lee" },
    },
  ],
};
