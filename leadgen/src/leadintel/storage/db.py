"""PostgreSQL connections and per-request security context."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import DictRow, dict_row

from leadintel.core.config import Settings
from leadintel.core.errors import ConfigurationError
from leadintel.security.authz import Principal

Connection = psycopg.Connection[DictRow]


def connect(dsn: str, *, application_name: str = "leadintel") -> Connection:
    return psycopg.connect(
        dsn, row_factory=dict_row, application_name=application_name, connect_timeout=10
    )


def dsn_from_settings(settings: Settings, *, secrets: Any = None, rds_client: Any = None) -> str:
    if settings.database_url is not None:
        return settings.database_url.get_secret_value()
    if settings.db_iam_user and settings.db_proxy_host:
        # IAM auth to RDS Proxy: a 15-minute token instead of a stored password.
        if rds_client is None:
            import boto3

            rds_client = boto3.client("rds", region_name=settings.aws_region)
        token = rds_client.generate_db_auth_token(
            DBHostname=settings.db_proxy_host, Port=5432, DBUsername=settings.db_iam_user
        )
        return psycopg.conninfo.make_conninfo(
            host=settings.db_proxy_host,
            port=5432,
            dbname=settings.db_name,
            user=settings.db_iam_user,
            password=token,
            sslmode="require",
            connect_timeout=10,
        )
    if settings.db_secret_arn:
        from leadintel.security.keyring import build_secrets_provider
        from leadintel.storage.migrate import dsn_from_rds_secret

        provider = secrets or build_secrets_provider(settings)
        return dsn_from_rds_secret(
            provider.get(settings.db_secret_arn), host_override=settings.db_proxy_host
        )
    raise ConfigurationError("no database configured (database_url or db_secret_arn)")


def _uuid_or_blank(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return ""


@contextmanager
def principal_scope(conn: Connection, principal: Principal) -> Iterator[Connection]:
    """One transaction with the caller's identity and row scope set for RLS.

    ``set_config(..., is_local => true)`` confines the settings to this
    transaction, so a pooled connection cannot leak one caller's scope to the next.
    """
    with conn.transaction():
        conn.execute(
            "SELECT set_config('app.user_id', %s, true),"
            "       set_config('app.scope', %s, true),"
            "       set_config('app.territories', %s, true)",
            (
                _uuid_or_blank(principal.subject),
                principal.row_scope,
                ",".join(sorted(t for t in principal.territories if _uuid_or_blank(t))),
            ),
        )
        yield conn
