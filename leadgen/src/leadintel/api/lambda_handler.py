"""Lambda entry point: API Gateway HTTP API (payload v2) -> ASGI via Mangum.

The app is built at import time so the cost (Secrets Manager, KMS, JWKS) is
paid once per container, during the init phase.
"""

from __future__ import annotations

from mangum import Mangum

from leadintel.api.app import create_app

app = create_app()
handler = Mangum(app, lifespan="off")
