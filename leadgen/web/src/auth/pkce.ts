/** OAuth 2.0 PKCE helpers (RFC 7636) built on WebCrypto. */

const VERIFIER_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~";

export function base64UrlEncode(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** A random string over the RFC 7636 unreserved alphabet (rejection sampling, no modulo bias). */
export function randomString(length = 64): string {
  if (length < 43 || length > 128) {
    throw new RangeError("PKCE strings must be 43-128 characters");
  }
  const out: string[] = [];
  const limit = 256 - (256 % VERIFIER_ALPHABET.length);
  while (out.length < length) {
    for (const byte of crypto.getRandomValues(new Uint8Array(length))) {
      if (byte < limit && out.length < length) {
        out.push(VERIFIER_ALPHABET[byte % VERIFIER_ALPHABET.length] as string);
      }
    }
  }
  return out.join("");
}

/** S256 code challenge: BASE64URL(SHA-256(ASCII(verifier))). */
export async function codeChallenge(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64UrlEncode(new Uint8Array(digest));
}
