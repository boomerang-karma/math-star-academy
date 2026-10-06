import { describe, expect, it, vi } from "vitest";

import type { AuthEnvironment, KeyValueStore } from "./auth";
import { AuthCallbackError, CognitoAuth, DevAuth, LoginRequiredError, safeReturnPath } from "./auth";

const CONFIG = {
  authMode: "cognito" as const,
  environment: "dev",
  cognitoDomain: "leadintel-dev.auth.eu-west-1.amazoncognito.com",
  clientId: "abc123client",
};

function memoryStore(): KeyValueStore & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (k) => data.get(k) ?? null,
    setItem: (k, v) => void data.set(k, v),
    removeItem: (k) => void data.delete(k),
  };
}

function tokenResponse(body: Record<string, unknown>, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function setup(fetchImpl?: typeof fetch) {
  const navigate = vi.fn<(url: string) => void>();
  let now = 1_000_000;
  const env: AuthEnvironment = {
    origin: "https://leads.example.com",
    fetch: fetchImpl ?? vi.fn<typeof fetch>(),
    navigate,
    session: memoryStore(),
    persistent: memoryStore(),
    now: () => now,
  };
  return {
    env,
    navigate,
    auth: new CognitoAuth(CONFIG, env),
    advance: (ms: number) => {
      now += ms;
    },
  };
}

async function signIn(ctx: ReturnType<typeof setup>, returnTo = "/leads/42?tab=graph") {
  await ctx.auth.login(returnTo);
  const authorizeUrl = new URL(ctx.navigate.mock.calls[0]?.[0] as string);
  const state = authorizeUrl.searchParams.get("state") as string;
  const resumed = await ctx.auth.handleCallback(
    new URL(`https://leads.example.com/auth/callback?code=the-code&state=${state}`),
  );
  return { authorizeUrl, resumed };
}

describe("CognitoAuth", () => {
  it("runs the authorization code + PKCE flow and resumes where the user was", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () =>
      tokenResponse({ access_token: "access-1", refresh_token: "refresh-1", expires_in: 3600 }),
    );
    const ctx = setup(fetchMock);
    const { authorizeUrl, resumed } = await signIn(ctx);

    expect(authorizeUrl.origin).toBe("https://leadintel-dev.auth.eu-west-1.amazoncognito.com");
    expect(authorizeUrl.pathname).toBe("/oauth2/authorize");
    expect(authorizeUrl.searchParams.get("code_challenge_method")).toBe("S256");
    expect(authorizeUrl.searchParams.get("redirect_uri")).toBe("https://leads.example.com/auth/callback");
    expect(resumed).toBe("/leads/42?tab=graph");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://leadintel-dev.auth.eu-west-1.amazoncognito.com/oauth2/token");
    const body = init.body as URLSearchParams;
    expect(body.get("grant_type")).toBe("authorization_code");
    expect(body.get("code")).toBe("the-code");
    expect(body.get("code_verifier")).toMatch(/^[A-Za-z0-9\-._~]{96}$/);
    expect(await ctx.auth.requestHeaders()).toEqual({ Authorization: "Bearer access-1" });
  });

  it("rejects a callback whose state does not match (login CSRF)", async () => {
    const ctx = setup(vi.fn<typeof fetch>());
    await ctx.auth.login("/");
    await expect(
      ctx.auth.handleCallback(new URL("https://leads.example.com/auth/callback?code=x&state=forged")),
    ).rejects.toBeInstanceOf(AuthCallbackError);
    expect(ctx.env.fetch).not.toHaveBeenCalled();
  });

  it("treats the login transaction as single-use", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => tokenResponse({ access_token: "a", expires_in: 3600 }));
    const ctx = setup(fetchMock);
    await ctx.auth.login("/");
    const state = new URL(ctx.navigate.mock.calls[0]?.[0] as string).searchParams.get("state");
    const callback = new URL(`https://leads.example.com/auth/callback?code=c&state=${state}`);
    await ctx.auth.handleCallback(callback);
    await expect(ctx.auth.handleCallback(callback)).rejects.toBeInstanceOf(AuthCallbackError);
  });

  it("refreshes an expiring token once, even with concurrent callers", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(tokenResponse({ access_token: "access-1", refresh_token: "refresh-1", expires_in: 3600 }))
      .mockResolvedValueOnce(tokenResponse({ access_token: "access-2", expires_in: 3600 }));
    const ctx = setup(fetchMock);
    await signIn(ctx);
    ctx.advance(3600 * 1000);
    const [a, b] = await Promise.all([ctx.auth.requestHeaders(), ctx.auth.requestHeaders()]);
    expect(a).toEqual({ Authorization: "Bearer access-2" });
    expect(b).toEqual(a);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const refreshBody = (fetchMock.mock.calls[1] as [string, RequestInit])[1].body as URLSearchParams;
    expect(refreshBody.get("grant_type")).toBe("refresh_token");
    expect(refreshBody.get("refresh_token")).toBe("refresh-1");
  });

  it("requires a new login when the refresh token is rejected", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(tokenResponse({ access_token: "a", refresh_token: "r", expires_in: 60 }))
      .mockResolvedValueOnce(tokenResponse({ error: "invalid_grant" }, 400));
    const ctx = setup(fetchMock);
    await signIn(ctx);
    ctx.advance(61_000);
    await expect(ctx.auth.requestHeaders()).rejects.toBeInstanceOf(LoginRequiredError);
    expect(ctx.auth.isAuthenticated()).toBe(false);
  });

  it("revokes the refresh token and ends the Hosted UI session on logout", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(tokenResponse({ access_token: "a", refresh_token: "r", expires_in: 3600 }))
      .mockResolvedValueOnce(new Response(null, { status: 200 }));
    const ctx = setup(fetchMock);
    await signIn(ctx);
    await ctx.auth.logout();
    const [url, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toMatch(/\/oauth2\/revoke$/);
    expect((init.body as URLSearchParams).get("token")).toBe("r");
    const logout = new URL(ctx.navigate.mock.calls[1]?.[0] as string);
    expect(logout.pathname).toBe("/logout");
    expect(logout.searchParams.get("logout_uri")).toBe("https://leads.example.com/");
    expect(ctx.auth.isAuthenticated()).toBe(false);
  });
});

describe("safeReturnPath", () => {
  it.each([
    ["/leads?tier=A", "/leads?tier=A"],
    ["//evil.example", "/"],
    ["https://evil.example/", "/"],
    ["/\\evil.example", "/"],
    ["", "/"],
    [null, "/"],
  ])("%s -> %s", (input, expected) => {
    expect(safeReturnPath(input)).toBe(expected);
  });
});

describe("DevAuth", () => {
  it("sends the persona as x-dev-* headers", async () => {
    const auth = new DevAuth({ persistent: memoryStore() });
    expect(await auth.requestHeaders()).toMatchObject({ "x-dev-roles": "admin" });
    auth.setIdentity({ user: "u-1", roles: ["sales_rep"], territories: ["t-1", "t-2"] });
    expect(await auth.requestHeaders()).toEqual({
      "x-dev-user": "u-1",
      "x-dev-roles": "sales_rep",
      "x-dev-territories": "t-1,t-2",
    });
  });
});
