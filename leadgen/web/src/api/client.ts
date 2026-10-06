/** Typed client for the LeadIntel API, mapping RFC 7807 problems to ApiError. */

import type { AuthSession } from "../auth/auth";
import { LoginRequiredError } from "../auth/auth";
import type {
  AccountBrief,
  EntityDetail,
  Graph,
  Lead360,
  LeadStatus,
  LeadSummary,
  Me,
  Page,
  Problem,
  ReviewItem,
  SearchHit,
  Tier,
} from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly requestId: string | null = null,
    readonly details: Record<string, unknown> | null = null,
  ) {
    super(message);
  }

  static async from(response: Response): Promise<ApiError> {
    let problem: Partial<Problem> = {};
    try {
      problem = (await response.json()) as Partial<Problem>;
    } catch {
      // Not JSON (e.g. a gateway error page): fall back to the status line.
    }
    const code = problem.type?.split("/").pop() ?? `http_${response.status}`;
    return new ApiError(
      response.status,
      code,
      problem.detail ?? (response.statusText || `HTTP ${response.status}`),
      problem.request_id ?? response.headers.get("x-request-id"),
      problem.details ?? null,
    );
  }
}

export interface LeadFilters {
  tier?: Tier | undefined;
  status?: LeadStatus | undefined;
  hot?: boolean | undefined;
  q?: string | undefined;
  cursor?: string | undefined;
  limit?: number | undefined;
}

type Query = Record<string, string | number | boolean | undefined>;

export class ApiClient {
  constructor(
    private readonly auth: AuthSession,
    private readonly fetcher: typeof fetch = (input, init) => fetch(input, init),
    private readonly onUnauthorized: () => void = () => {},
    private readonly base = "/api",
  ) {}

  me(): Promise<Me> {
    return this.request("GET", "/v1/me");
  }

  leads(filters: LeadFilters = {}): Promise<Page<LeadSummary>> {
    return this.request("GET", "/v1/leads", { query: { ...filters } });
  }

  lead(id: string): Promise<Lead360> {
    return this.request("GET", `/v1/leads/${encodeURIComponent(id)}`);
  }

  updateLead(id: string, patch: { status?: LeadStatus }): Promise<{ updated: boolean }> {
    return this.request("PATCH", `/v1/leads/${encodeURIComponent(id)}`, { body: patch });
  }

  generateBrief(id: string): Promise<AccountBrief> {
    return this.request("POST", `/v1/leads/${encodeURIComponent(id)}/brief`, { body: {} });
  }

  entity(id: string): Promise<EntityDetail> {
    return this.request("GET", `/v1/entities/${encodeURIComponent(id)}`);
  }

  entityGraph(id: string, depth: 1 | 2): Promise<Graph> {
    return this.request("GET", `/v1/entities/${encodeURIComponent(id)}/graph`, {
      query: { depth },
    });
  }

  search(q: string): Promise<{ items: SearchHit[] }> {
    return this.request("GET", "/v1/search", { query: { q } });
  }

  reviews(): Promise<{ items: ReviewItem[] }> {
    return this.request("GET", "/v1/review");
  }

  decideReview(id: string, decision: "accept" | "reject"): Promise<{ decision: string }> {
    return this.request("POST", `/v1/review/${encodeURIComponent(id)}`, { body: { decision } });
  }

  async request<T>(
    method: "GET" | "POST" | "PATCH",
    path: string,
    options: { query?: Query; body?: unknown } = {},
  ): Promise<T> {
    const url = new URL(this.base + path, "http://placeholder");
    for (const [key, value] of Object.entries(options.query ?? {})) {
      if (value !== undefined && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
    let headers: Record<string, string>;
    try {
      headers = { Accept: "application/json", ...(await this.auth.requestHeaders()) };
    } catch (err) {
      if (err instanceof LoginRequiredError) {
        this.onUnauthorized();
      }
      throw err;
    }
    const init: RequestInit = { method, headers, credentials: "same-origin" };
    if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }
    const response = await this.fetcher(url.pathname + url.search, init);
    if (!response.ok) {
      if (response.status === 401) {
        this.onUnauthorized();
      }
      throw await ApiError.from(response);
    }
    return (await response.json()) as T;
  }
}
