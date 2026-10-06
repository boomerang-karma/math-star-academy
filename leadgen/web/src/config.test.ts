import { describe, expect, it } from "vitest";

import { ConfigError, parseConfig } from "./config";

describe("runtime config", () => {
  it("accepts local-dev and cognito configs", () => {
    expect(parseConfig({ authMode: "local-dev" })).toEqual({ authMode: "local-dev", environment: "local" });
    expect(
      parseConfig({
        authMode: "cognito",
        environment: "prod",
        cognitoDomain: "leadintel-prod.auth.eu-west-1.amazoncognito.com",
        clientId: "4h3k2j1",
      }),
    ).toMatchObject({ authMode: "cognito", clientId: "4h3k2j1" });
  });

  it("rejects anything that could redirect sign-in elsewhere", () => {
    expect(() => parseConfig({ authMode: "basic" })).toThrow(ConfigError);
    expect(() => parseConfig({ authMode: "cognito", cognitoDomain: "evil.example/path", clientId: "x" })).toThrow(
      ConfigError,
    );
    expect(() => parseConfig({ authMode: "cognito", cognitoDomain: "a.example" })).toThrow(ConfigError);
    expect(() => parseConfig(null)).toThrow(ConfigError);
  });
});
