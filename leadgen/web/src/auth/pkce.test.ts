import { describe, expect, it } from "vitest";

import { base64UrlEncode, codeChallenge, randomString } from "./pkce";

describe("pkce", () => {
  it("matches the RFC 7636 appendix B test vector", async () => {
    expect(await codeChallenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")).toBe(
      "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
    );
  });

  it("base64url-encodes without padding or unsafe characters", () => {
    expect(base64UrlEncode(new Uint8Array([251, 255, 191]))).toBe("-_-_");
    expect(base64UrlEncode(new Uint8Array([1]))).toBe("AQ");
  });

  it("generates verifiers of the requested length over the unreserved alphabet", () => {
    const values = new Set<string>();
    for (let i = 0; i < 50; i++) {
      const value = randomString(64);
      expect(value).toMatch(/^[A-Za-z0-9\-._~]{64}$/);
      values.add(value);
    }
    expect(values.size).toBe(50);
  });

  it("rejects lengths outside RFC 7636 bounds", () => {
    expect(() => randomString(42)).toThrow(RangeError);
    expect(() => randomString(129)).toThrow(RangeError);
  });
});
