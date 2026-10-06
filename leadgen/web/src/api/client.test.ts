import { describe, expect, it, vi } from "vitest";

import type { AuthSession } from "../auth/auth";
import { LoginRequiredError } from "../auth/auth";
import { ApiClient, ApiError } from "./client";

function fakeAuth(headers: Record<string, string> | Error = { Authorization: "Bearer t" }): AuthSession {
  return {
    mode: "cognito",
    isAuthenticated: () => true,
    requestHeaders: async () => {
      if (headers instanceof Error) {
        throw headers;
      }
      return headers;
    },
    login: async () => {},
    logout: async () => {},
  };
}

function json(body: unknown, status = 200, contentType = "application/json"): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": contentType } });
}

describe("ApiClient", () => {
  it("builds query strings, skipping empty filters, and sends credentials", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => json({ items: [], next_cursor: null }));
    const api = new ApiClient(fakeAuth(), fetchMock);
    await api.leads({ tier: "A", status: undefined, hot: true, q: "", limit: 50 });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/leads?tier=A&hot=true&limit=50");
    expect(init.method).toBe("GET");
    expect(init.headers).toMatchObject({ Authorization: "Bearer t", Accept: "application/json" });
    expect(init.body).toBeUndefined();
  });

  it("encodes path segments", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => json({}));
    await new ApiClient(fakeAuth(), fetchMock).entity("../admin");
    expect((fetchMock.mock.calls[0] as [string])[0]).toBe("/api/v1/entities/..%2Fadmin");
  });

  it("sends JSON bodies for writes", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => json({ updated: true }));
    await new ApiClient(fakeAuth(), fetchMock).updateLead("l-1", { status: "working" });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("PATCH");
    expect(init.body).toBe('{"status":"working"}');
    expect(init.headers).toMatchObject({ "Content-Type": "application/json" });
  });

  it("maps RFC 7807 problems to ApiError", async () => {
    const problem = {
      type: "https://leadintel.dev/problems/forbidden",
      title: "forbidden",
      status: 403,
      detail: "missing permission",
      request_id: "req-1",
      details: { missing: ["entities:merge"] },
    };
    const api = new ApiClient(fakeAuth(), async () => json(problem, 403, "application/problem+json"));
    const error = await api.reviews().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 403,
      code: "forbidden",
      message: "missing permission",
      requestId: "req-1",
      details: { missing: ["entities:merge"] },
    });
  });

  it("survives non-JSON error bodies", async () => {
    const api = new ApiClient(fakeAuth(), async () => new Response("<html>bad gateway</html>", { status: 502 }));
    await expect(api.me()).rejects.toMatchObject({ status: 502, code: "http_502" });
  });

  it("signals re-authentication on 401 and when no session exists", async () => {
    const onUnauthorized = vi.fn();
    const api = new ApiClient(fakeAuth(), async () => json({ status: 401 }, 401), onUnauthorized);
    await expect(api.me()).rejects.toBeInstanceOf(ApiError);
    const anonymous = new ApiClient(fakeAuth(new LoginRequiredError()), vi.fn<typeof fetch>(), onUnauthorized);
    await expect(anonymous.me()).rejects.toBeInstanceOf(LoginRequiredError);
    expect(onUnauthorized).toHaveBeenCalledTimes(2);
  });
});
