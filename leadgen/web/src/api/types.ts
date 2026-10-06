/** Wire types for the LeadIntel API (see src/leadintel/api/views.py and routers/). */

export type Tier = "A" | "B" | "C" | "D";
export type LeadStatus =
  | "new"
  | "working"
  | "nurture"
  | "qualified"
  | "disqualified"
  | "converted";
export type EntityType = "organization" | "person";

export const LEAD_STATUSES: readonly LeadStatus[] = [
  "new",
  "working",
  "nurture",
  "qualified",
  "disqualified",
  "converted",
];

export interface Me {
  subject: string;
  roles: string[];
  permissions: string[];
  territories: string[];
  row_scope: "global" | "territory";
}

export interface LeadSummary {
  id: string;
  status: LeadStatus;
  tier: Tier | null;
  score: number | null;
  fit: number | null;
  intent: number | null;
  engagement: number | null;
  hot: boolean;
  scored_at: string | null;
  organization: {
    id: string | null;
    name: string | null;
    domain: string | null;
    industry: string | null;
    country: string | null;
    employees: number | null;
  };
  person: { id: string; name: string | null; title: string | null } | null;
  last_signal_at: string | null;
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

export interface AlternativeValue {
  value: unknown;
  source: string | null;
  observed_at: string | null;
}

export interface AttributeView {
  value: unknown;
  source: string | null;
  observed_at: string | null;
  record_id: string | null;
  confidence: number | null;
  agreeing_sources: number;
  alternatives: AlternativeValue[];
}

export interface Contact {
  email: string | null;
  phone: string | null;
  masked: boolean;
}

export interface EntityView {
  id: string;
  type: EntityType;
  display_name: string | null;
  status: string;
  merged_into: string | null;
  domain: string | null;
  attributes: Record<string, AttributeView>;
  contact: Contact | null;
  updated_at: string | null;
}

export interface SignalView {
  id: string;
  type: string;
  source: string;
  occurred_at: string;
  title: string | null;
  url: string | null;
  strength: number;
  entity_id: string | null;
}

export interface GraphNode {
  id: string;
  type: EntityType;
  label: string | null;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  properties: Record<string, unknown>;
  provenance: string;
  confidence: number;
}

export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface Contribution {
  component: "fit" | "intent" | "engagement" | string;
  factor: string;
  points: number;
  detail: string;
}

export interface ConsentEntry {
  purpose: string;
  status: string;
  source: string;
  captured_at: string;
}

export interface AccountBrief {
  summary: string;
  why_now: string[];
  talking_points: string[];
  risks: string[];
  recommended_next_step: string;
  confidence: "low" | "medium" | "high";
  model: string;
  generated_at?: string;
  cached?: boolean;
}

export interface Lead360 {
  lead: {
    id: string;
    status: LeadStatus;
    tier: Tier | null;
    score: number | null;
    components: { fit: number; intent: number; engagement: number };
    hot: boolean;
    explanation: Contribution[] | null;
    scored_at: string | null;
    territory: string | null;
    owner: { id: string; name: string | null } | null;
    history: { at: string; score: number; tier: Tier }[];
  };
  organization: EntityView | null;
  person: EntityView | null;
  signals: SignalView[];
  graph: Graph;
  consent: ConsentEntry[];
  suppressed: boolean;
  brief: AccountBrief | null;
}

/** One log-odds term from entity resolution (pipeline/resolution/matching.py). */
export interface Evidence {
  feature: string;
  weight: number;
  detail: string;
}

export interface LineageEntry {
  record_id: string;
  source: string;
  observed_at: string;
  fetched_at: string;
  source_url: string | null;
  lawful_basis: string;
  match: {
    method: string;
    probability: number;
    evidence: Evidence[] | null;
    decided_by: string | null;
  };
}

export interface EntityDetail extends EntityView {
  lineage: LineageEntry[];
  signals: SignalView[];
}

export interface SearchHit {
  id: string;
  type: EntityType;
  name: string | null;
  domain: string | null;
}

export interface ReviewItem {
  id: string;
  probability: number;
  evidence: Evidence[] | null;
  entity_type: EntityType;
  record_source: string;
  record_entity: { id: string; name: string | null };
  candidate_entity: { id: string; name: string | null };
}

/** RFC 7807 problem details, as rendered by src/leadintel/api/middleware.py. */
export interface Problem {
  type?: string;
  title?: string;
  status: number;
  detail?: string;
  request_id?: string;
  details?: Record<string, unknown>;
}
