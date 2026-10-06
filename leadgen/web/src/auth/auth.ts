/**
 * Authentication for the SPA.
 *
 * Cognito: authorization code + PKCE against the Hosted UI (public client, no
 * secret). Tokens live in sessionStorage, so they are scoped to the tab and gone
 * when it closes; the strict CSP (script-src 'self') is what keeps other scripts
 * away from them. Access tokens last an hour and are refreshed on demand;
 * logout revokes the refresh token before ending the Hosted UI session.
 *
 * Local dev: no login. A persona picker sets the x-dev-* identity headers that
 * the API honours only when LEADINTEL_AUTH_MODE=local-dev (refused outside the
 * local environment).
 */

import type { RuntimeConfig } from "../config";
import { codeChallenge, randomString } from "./pkce";

export class LoginRequiredError extends Error {
  constructor() {
    super("login required");
  }
}

export class AuthCallbackError extends Error {}

export interface KeyValueStore {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export interface AuthEnvironment {
  origin: string;
  fetch: typeof fetch;
  navigate: (url: string) => void;
  session: KeyValueStore;
  persistent: KeyValueStore;
  now: () => number;
}

export interface DevIdentity {
  user: string;
  roles: string[];
  territories: string[];
}

export interface AuthSession {
  readonly mode: RuntimeConfig["authMode"];
  isAuthenticated(): boolean;
  /** Headers that authenticate an API call; throws LoginRequiredError when there are none. */
  requestHeaders(): Promise<Record<string, string>>;
  login(returnTo: string): Promise<void>;
  logout(): Promise<void>;
}

const TOKENS_KEY = "leadintel.auth.tokens";
const TXN_KEY = "leadintel.auth.txn";
const DEV_KEY = "leadintel.dev.identity";
const REFRESH_SKEW_MS = 60_000;

interface StoredTokens {
  accessToken: string;
  refreshToken?: string;
  expiresAt: number;
}

interface LoginTransaction {
  state: string;
  verifier: string;
  returnTo: string;
}

function readJson<T>(store: KeyValueStore, key: string): T | null {
  try {
    const raw = store.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null; // storage unavailable (private mode, blocked site data) or corrupt
  }
}

function writeJson(store: KeyValueStore, key: string, value: unknown): void {
  try {
    store.setItem(key, JSON.stringify(value));
  } catch {
    // Storage unavailable: the session lasts until reload, which is acceptable.
  }
}

function remove(store: KeyValueStore, key: string): void {
  try {
    store.removeItem(key);
  } catch {
    // ignore
  }
}

/** Only same-origin absolute paths survive the round trip (no open redirects). */
export function safeReturnPath(candidate: string | null | undefined): string {
  if (!candidate || !candidate.startsWith("/") || candidate.startsWith("//")) {
    return "/";
  }
  if (candidate.includes("\\") || /[\u0000-\u001f]/.test(candidate)) {
    return "/";
  }
  return candidate;
}

export class CognitoAuth implements AuthSession {
  readonly mode = "cognito" as const;
  private tokens: StoredTokens | null;
  private refreshing: Promise<StoredTokens> | null = null;
  private readonly domain: string;
  private readonly clientId: string;

  constructor(
    config: RuntimeConfig,
    private readonly env: AuthEnvironment,
  ) {
    if (!config.cognitoDomain || !config.clientId) {
      throw new Error("Cognito configuration is incomplete");
    }
    this.domain = config.cognitoDomain;
    this.clientId = config.clientId;
    this.tokens = readJson<StoredTokens>(env.session, TOKENS_KEY);
  }

  get redirectUri(): string {
    return `${this.env.origin}/auth/callback`;
  }

  isAuthenticated(): boolean {
    return this.tokens !== null;
  }

  async login(returnTo: string): Promise<void> {
    const txn: LoginTransaction = {
      state: randomString(43),
      verifier: randomString(96),
      returnTo: safeReturnPath(returnTo),
    };
    writeJson(this.env.session, TXN_KEY, txn);
    const params = new URLSearchParams({
      response_type: "code",
      client_id: this.clientId,
      redirect_uri: this.redirectUri,
      scope: "openid email profile",
      state: txn.state,
      code_challenge: await codeChallenge(txn.verifier),
      code_challenge_method: "S256",
    });
    this.env.navigate(`https://${this.domain}/oauth2/authorize?${params.toString()}`);
  }

  /** Complete the redirect from the Hosted UI; returns the path to resume at. */
  async handleCallback(url: URL): Promise<string> {
    const txn = readJson<LoginTransaction>(this.env.session, TXN_KEY);
    remove(this.env.session, TXN_KEY); // one use only, whatever happens next
    const error = url.searchParams.get("error");
    if (error) {
      throw new AuthCallbackError(url.searchParams.get("error_description") ?? error);
    }
    const code = url.searchParams.get("code");
    const state = url.searchParams.get("state");
    if (!txn || !code || !state || state !== txn.state) {
      throw new AuthCallbackError("sign-in response did not match a pending sign-in");
    }
    this.store(
      await this.tokenRequest({
        grant_type: "authorization_code",
        client_id: this.clientId,
        code,
        redirect_uri: this.redirectUri,
        code_verifier: txn.verifier,
      }),
    );
    return safeReturnPath(txn.returnTo);
  }

  async requestHeaders(): Promise<Record<string, string>> {
    let tokens = this.tokens;
    if (!tokens) {
      throw new LoginRequiredError();
    }
    if (tokens.expiresAt - REFRESH_SKEW_MS <= this.env.now()) {
      tokens = await this.refresh(tokens);
    }
    return { Authorization: `Bearer ${tokens.accessToken}` };
  }

  /** Called after a 401: the token was revoked or the clock lied. */
  invalidate(): void {
    this.tokens = null;
    remove(this.env.session, TOKENS_KEY);
  }

  async logout(): Promise<void> {
    const refreshToken = this.tokens?.refreshToken;
    this.invalidate();
    if (refreshToken) {
      try {
        await this.env.fetch(`https://${this.domain}/oauth2/revoke`, {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: new URLSearchParams({ token: refreshToken, client_id: this.clientId }),
        });
      } catch {
        // Best effort: the Hosted UI logout below still ends the session.
      }
    }
    const params = new URLSearchParams({
      client_id: this.clientId,
      logout_uri: `${this.env.origin}/`,
    });
    this.env.navigate(`https://${this.domain}/logout?${params.toString()}`);
  }

  private async refresh(current: StoredTokens): Promise<StoredTokens> {
    if (!current.refreshToken) {
      this.invalidate();
      throw new LoginRequiredError();
    }
    if (!this.refreshing) {
      const refreshToken = current.refreshToken;
      this.refreshing = this.tokenRequest({
        grant_type: "refresh_token",
        client_id: this.clientId,
        refresh_token: refreshToken,
      })
        .then((fresh) => this.store({ ...fresh, refreshToken: fresh.refreshToken ?? refreshToken }))
        .catch((err: unknown) => {
          this.invalidate();
          throw err instanceof LoginRequiredError ? err : new LoginRequiredError();
        })
        .finally(() => {
          this.refreshing = null;
        });
    }
    return this.refreshing;
  }

  private async tokenRequest(body: Record<string, string>): Promise<StoredTokens> {
    const response = await this.env.fetch(`https://${this.domain}/oauth2/token`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams(body),
    });
    if (!response.ok) {
      throw new AuthCallbackError(`token endpoint returned HTTP ${response.status}`);
    }
    const payload = (await response.json()) as Record<string, unknown>;
    const accessToken = payload["access_token"];
    const expiresIn = payload["expires_in"];
    if (typeof accessToken !== "string" || typeof expiresIn !== "number") {
      throw new AuthCallbackError("token endpoint returned an unexpected response");
    }
    const tokens: StoredTokens = {
      accessToken,
      expiresAt: this.env.now() + expiresIn * 1000,
    };
    if (typeof payload["refresh_token"] === "string") {
      tokens.refreshToken = payload["refresh_token"];
    }
    return tokens;
  }

  private store(tokens: StoredTokens): StoredTokens {
    this.tokens = tokens;
    writeJson(this.env.session, TOKENS_KEY, tokens);
    return tokens;
  }
}

// UUID subjects, so lead ownership and RLS behave as they do with Cognito users.
export const DEV_PERSONAS: Record<string, DevIdentity> = {
  admin: { user: "00000000-0000-4000-8000-000000000001", roles: ["admin"], territories: [] },
  analyst: { user: "00000000-0000-4000-8000-000000000002", roles: ["analyst"], territories: [] },
  sales_rep: {
    user: "00000000-0000-4000-8000-000000000003",
    roles: ["sales_rep"],
    territories: [],
  },
  compliance_officer: {
    user: "00000000-0000-4000-8000-000000000004",
    roles: ["compliance_officer"],
    territories: [],
  },
  viewer: { user: "00000000-0000-4000-8000-000000000005", roles: ["viewer"], territories: [] },
};

export class DevAuth implements AuthSession {
  readonly mode = "local-dev" as const;

  constructor(private readonly env: Pick<AuthEnvironment, "persistent">) {}

  get identity(): DevIdentity {
    const stored = readJson<DevIdentity>(this.env.persistent, DEV_KEY);
    return stored ?? (DEV_PERSONAS["admin"] as DevIdentity);
  }

  setIdentity(identity: DevIdentity): void {
    writeJson(this.env.persistent, DEV_KEY, identity);
  }

  isAuthenticated(): boolean {
    return true;
  }

  async requestHeaders(): Promise<Record<string, string>> {
    const { user, roles, territories } = this.identity;
    const headers: Record<string, string> = { "x-dev-user": user, "x-dev-roles": roles.join(",") };
    if (territories.length > 0) {
      headers["x-dev-territories"] = territories.join(",");
    }
    return headers;
  }

  async login(): Promise<void> {}

  async logout(): Promise<void> {}
}

export function browserEnvironment(): AuthEnvironment {
  const memory = new Map<string, string>();
  const fallback: KeyValueStore = {
    getItem: (k) => memory.get(k) ?? null,
    setItem: (k, v) => void memory.set(k, v),
    removeItem: (k) => void memory.delete(k),
  };
  const pick = (get: () => Storage): KeyValueStore => {
    try {
      const store = get();
      store.getItem("leadintel.probe");
      return store;
    } catch {
      return fallback;
    }
  };
  return {
    origin: window.location.origin,
    fetch: window.fetch.bind(window),
    navigate: (url) => window.location.assign(url),
    session: pick(() => window.sessionStorage),
    persistent: pick(() => window.localStorage),
    now: () => Date.now(),
  };
}

export function createAuth(config: RuntimeConfig, env: AuthEnvironment): AuthSession {
  return config.authMode === "cognito" ? new CognitoAuth(config, env) : new DevAuth(env);
}
