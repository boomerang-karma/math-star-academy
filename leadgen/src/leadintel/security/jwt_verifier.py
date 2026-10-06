"""Cognito access-token verification.

API Gateway's JWT authorizer already rejects bad tokens at the edge; the API
verifies again so a misconfigured route can never open the data plane.
"""

from __future__ import annotations

from typing import Any, Protocol

import jwt

from leadintel.core.errors import AuthenticationError


class SigningKeySource(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> Any: ...


class CognitoJwtVerifier:
    def __init__(
        self,
        *,
        region: str,
        user_pool_id: str,
        app_client_id: str,
        key_source: SigningKeySource | None = None,
        leeway_s: int = 30,
    ) -> None:
        self.issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        self._client_id = app_client_id
        self._keys = key_source or jwt.PyJWKClient(
            f"{self.issuer}/.well-known/jwks.json", cache_keys=True, lifespan=3600
        )
        self._leeway = leeway_s

    def verify(self, token: str) -> dict[str, Any]:
        try:
            signing_key = self._keys.get_signing_key_from_jwt(token)
            claims: dict[str, Any] = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=self.issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iat", "iss", "sub", "token_use"], "verify_aud": False},
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError("invalid token") from exc
        # Access tokens carry client_id instead of aud; ID tokens must not be accepted here.
        if claims.get("token_use") != "access":
            raise AuthenticationError("an access token is required")
        if claims.get("client_id") != self._client_id:
            raise AuthenticationError("token was issued to another client")
        return claims
