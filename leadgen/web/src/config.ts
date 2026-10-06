/**
 * Runtime configuration, fetched from /config.json at startup.
 *
 * The same build serves every environment: the CDK web stack writes config.json
 * next to index.html (Cognito domain and client id), and public/config.json
 * selects local-dev mode for `npm run dev`.
 */

export type AuthMode = "cognito" | "local-dev";

export interface RuntimeConfig {
  authMode: AuthMode;
  environment: string;
  cognitoDomain?: string;
  clientId?: string;
}

export class ConfigError extends Error {}

export function parseConfig(raw: unknown): RuntimeConfig {
  if (typeof raw !== "object" || raw === null) {
    throw new ConfigError("config.json must be an object");
  }
  const value = raw as Record<string, unknown>;
  const authMode = value["authMode"];
  if (authMode !== "cognito" && authMode !== "local-dev") {
    throw new ConfigError(`unsupported authMode: ${String(authMode)}`);
  }
  const environment = typeof value["environment"] === "string" ? value["environment"] : "local";
  if (authMode === "local-dev") {
    return { authMode, environment };
  }
  const cognitoDomain = value["cognitoDomain"];
  const clientId = value["clientId"];
  if (typeof cognitoDomain !== "string" || !/^[a-z0-9.-]+$/.test(cognitoDomain)) {
    throw new ConfigError("cognitoDomain must be a bare host name");
  }
  if (typeof clientId !== "string" || !/^[A-Za-z0-9]+$/.test(clientId)) {
    throw new ConfigError("clientId is missing or malformed");
  }
  return { authMode, environment, cognitoDomain, clientId };
}

export async function loadConfig(fetcher: typeof fetch = fetch): Promise<RuntimeConfig> {
  const response = await fetcher("/config.json", { cache: "no-store" });
  if (!response.ok) {
    throw new ConfigError(`could not load config.json (HTTP ${response.status})`);
  }
  return parseConfig(await response.json());
}
