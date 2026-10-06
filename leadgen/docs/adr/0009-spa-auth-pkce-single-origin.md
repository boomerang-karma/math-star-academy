# 0009. Single-origin SPA with Cognito PKCE

**Status:** Accepted

## Context

The UI is a single-page app for authenticated staff. We want strong
authentication (MFA), no CORS complexity, edge protection (WAF), and minimal
token exposure.

## Decision

- **One origin.** A single CloudFront distribution serves the SPA (private S3
  through OAC) and proxies `/api/*` to API Gateway. Same origin means no CORS
  and no third-party cookies.
- **Sign-in.** Cognito Hosted UI with the authorization code flow and PKCE
  (public client, no secret).
- **Tokens.** Access tokens last 1 hour and live in `sessionStorage` (tab
  scoped). Refresh tokens last 12 hours and are revoked on logout. The API
  accepts only access tokens for this client.
- **CSP.** A strict policy (`script-src 'self'`, no inline scripts or styles),
  verified by browser tests against the production build.
- **Runtime config.** `config.json` is written at deploy time, so one build
  serves every environment.

## Alternatives

- **Backend-for-frontend with HttpOnly session cookies.** Tokens never reach
  JavaScript, which is stronger against XSS, but it means a stateful session
  layer. This is the planned upgrade path (roadmap phase 4).
- **Implicit flow.** Deprecated and less secure.
- **Separate API domain.** Needs CORS and complicates the CSP and cookies.

## Consequences

- XSS is the main token risk, mitigated by the strict CSP and React escaping.
- Cognito domains and client ids are environment configuration, not build
  inputs.
