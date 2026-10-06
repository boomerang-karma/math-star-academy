from __future__ import annotations

import hashlib
import hmac
import logging
import socket
from datetime import UTC, datetime, timedelta

import boto3
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from moto import mock_aws

from leadintel.core.config import Settings
from leadintel.core.errors import AuthenticationError, ConfigurationError, ValidationFailedError
from leadintel.security.audit import AuditRow, canonical_line, chain_hash, verify_chain
from leadintel.security.authz import (
    Permission,
    Principal,
    Role,
    mask_email,
    mask_phone,
    principal_from_claims,
    require,
    roles_from_groups,
)
from leadintel.security.blind_index import BlindIndexer
from leadintel.security.jwt_verifier import CognitoJwtVerifier
from leadintel.security.redaction import RedactingFilter, redact
from leadintel.security.secrets import AwsSecretsManagerProvider
from leadintel.security.ssrf import validate_public_url
from leadintel.security.webhooks import (
    linkedin_challenge_response,
    verify_linkedin_signature,
    verify_timestamped_hmac,
)

# --- blind index -------------------------------------------------------------------


def test_blind_index_is_deterministic_and_field_separated(bidx: BlindIndexer) -> None:
    a = bidx.index("Jane@Acme.example ", field="email")
    assert a == bidx.index("jane@acme.example", field="email")
    assert a != bidx.index("jane@acme.example", field="phone")
    assert "jane" not in a


def test_blind_index_depends_on_key() -> None:
    k1, k2 = BlindIndexer(b"k" * 32), BlindIndexer(b"j" * 32)
    assert k1.index("x", field="f") != k2.index("x", field="f")


def test_blind_index_rejects_weak_key_and_empty_value(bidx: BlindIndexer) -> None:
    with pytest.raises(ConfigurationError):
        BlindIndexer(b"short")
    with pytest.raises(ValueError, match="empty"):
        bidx.index("   ", field="email")
    assert bidx.maybe_index(None, field="email") is None


# --- authorization -------------------------------------------------------------------


def _principal(*roles: Role) -> Principal:
    return Principal(subject="u1", roles=frozenset(roles), tenant_id="t")


def test_role_permissions() -> None:
    analyst = _principal(Role.ANALYST)
    rep = _principal(Role.SALES_REP)
    assert analyst.has(Permission.ENTITIES_MERGE)
    assert not analyst.has(Permission.PII_READ)  # analysts see masked contact data
    assert rep.has(Permission.PII_READ)
    assert not rep.has(Permission.COMPLIANCE_DSAR)
    assert _principal(Role.ADMIN).permissions == frozenset(Permission)


def test_row_scope() -> None:
    assert _principal(Role.SALES_REP).row_scope == "territory"
    assert _principal(Role.SALES_REP, Role.ANALYST).row_scope == "global"
    assert _principal().row_scope == "territory"


def test_require_raises_with_missing_permissions() -> None:
    with pytest.raises(Exception, match="missing permission") as info:
        require(_principal(Role.VIEWER), Permission.LEADS_READ, Permission.AUDIT_READ)
    assert info.value.details == {"missing": ["audit:read"]}  # type: ignore[attr-defined]


def test_roles_from_groups_ignores_unknown_groups() -> None:
    groups = ["leadintel-analyst", "leadintel-superuser", "other-admin", "leadintel-viewer"]
    assert roles_from_groups(groups) == {Role.ANALYST, Role.VIEWER}


def test_principal_from_claims_without_groups_has_no_permissions() -> None:
    principal = principal_from_claims({"sub": "abc"}, tenant_id="t")
    assert principal.permissions == frozenset()


def test_masking() -> None:
    assert mask_email("jane.doe@acme.example") == "j***@acme.example"
    assert mask_phone("+1 (415) 555-0100") == "+*******0100"
    assert mask_phone("123") == "***"
    assert mask_email(None) is None


# --- audit chain -----------------------------------------------------------------------


def _rows(n: int) -> list[AuditRow]:
    rows: list[AuditRow] = []
    prev: bytes | None = None
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for seq in range(1, n + 1):
        draft = AuditRow(
            seq=seq,
            occurred_at=start + timedelta(seconds=seq),
            actor_id="u1",
            actor_type="user",
            action="lead.view",
            resource_type="lead",
            resource_id=str(seq),
            outcome="success",
            request_id=None,
            ip=None,
            details_text="{}",
            prev_hash=prev,
            hash=b"",
        )
        digest = chain_hash(prev, canonical_line(draft))
        rows.append(
            AuditRow(**{**draft.__dict__, "hash": digest})  # type: ignore[arg-type]
        )
        prev = digest
    return rows


def test_audit_chain_verifies_and_detects_tampering() -> None:
    rows = _rows(5)
    assert verify_chain(rows) is None
    tampered = list(rows)
    tampered[2] = AuditRow(**{**rows[2].__dict__, "action": "lead.export"})  # type: ignore[arg-type]
    assert verify_chain(tampered) == 3
    assert verify_chain([rows[0], rows[2]]) == 3  # deleted row breaks the link


# --- SSRF guard ------------------------------------------------------------------------


def _resolver(*addresses: str):  # type: ignore[no-untyped-def]
    def resolve(host, port, proto=0):  # type: ignore[no-untyped-def]
        return [(socket.AF_INET, socket.SOCK_STREAM, proto, "", (a, port)) for a in addresses]

    return resolve


def test_ssrf_allows_public_https() -> None:
    url = "https://www.acme.example/about"
    assert validate_public_url(url, resolver=_resolver("93.184.216.34")) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://[::ffff:10.0.0.1]/",
        "https://100.64.1.1/",
        "file:///etc/passwd",
        "gopher://acme.example/",
        "https://user:pass@acme.example/",
        "https://acme.example:8443/",
    ],
)
def test_ssrf_blocks_dangerous_urls(url: str) -> None:
    with pytest.raises(ValidationFailedError):
        validate_public_url(url, resolver=_resolver("93.184.216.34"))


def test_ssrf_blocks_dns_names_resolving_to_private_ranges() -> None:
    with pytest.raises(ValidationFailedError, match="non-public"):
        validate_public_url("https://internal.acme.example", resolver=_resolver("10.0.3.7"))


# --- redaction -------------------------------------------------------------------------


def test_redaction_scrubs_identifiers_and_credentials() -> None:
    line = (
        "user jane.doe@acme.example called +1 415-555-0100 with key sb_live_abcdef123456 "
        "and Bearer eyJhbGciOi.eyJzdWIiOi.c2lnbmF0dXJl password=hunter22"
    )
    scrubbed = redact(line)
    for secret in ("jane.doe@", "555-0100", "sb_live_abc", "eyJhbGciOi", "hunter22"):
        assert secret not in scrubbed
    assert redact("lead 12 scored 87.5") == "lead 12 scored 87.5"


def test_redacting_filter_rewrites_records() -> None:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "mail %s", ("a@b.example",), None)
    RedactingFilter().filter(record)
    assert record.getMessage() == "mail [REDACTED_EMAIL]"


# --- webhooks --------------------------------------------------------------------------


def test_linkedin_challenge() -> None:
    body = linkedin_challenge_response("abc", "s3cret")
    expected = hmac.new(b"s3cret", b"abc", hashlib.sha256).hexdigest()
    assert body == {"challengeCode": "abc", "challengeResponse": expected}


def test_linkedin_signature() -> None:
    raw = b'{"leadGenFormResponse":"urn:li:leadGenFormResponse:1"}'
    good = hmac.new(b"s3cret", b"hmacsha256=" + raw, hashlib.sha256).hexdigest()
    verify_linkedin_signature(raw, good, "s3cret")
    verify_linkedin_signature(raw, "hmacsha256=" + good, "s3cret")
    with pytest.raises(AuthenticationError):
        verify_linkedin_signature(raw, good, "other-secret")
    with pytest.raises(AuthenticationError):
        verify_linkedin_signature(raw + b" ", good, "s3cret")
    with pytest.raises(AuthenticationError):
        verify_linkedin_signature(raw, None, "s3cret")


def test_timestamped_hmac_rejects_replays() -> None:
    body = b"{}"
    sig = hmac.new(b"k", b"1000." + body, hashlib.sha256).hexdigest()
    verify_timestamped_hmac(body, signature=sig, timestamp="1000", secret="k", clock=lambda: 1100)
    with pytest.raises(AuthenticationError, match="stale"):
        verify_timestamped_hmac(
            body, signature=sig, timestamp="1000", secret="k", clock=lambda: 2000
        )


# --- JWT -------------------------------------------------------------------------------


class _StaticKeys:
    def __init__(self, public_key: object) -> None:
        self.key = public_key

    def get_signing_key_from_jwt(self, token: str) -> _StaticKeys:
        return self


@pytest.fixture(scope="module")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(key: rsa.RSAPrivateKey, **claims: object) -> str:
    now = int(datetime.now(UTC).timestamp())
    body = {
        "sub": "user-1",
        "iss": "https://cognito-idp.us-east-1.amazonaws.com/pool",
        "token_use": "access",
        "client_id": "client",
        "iat": now,
        "exp": now + 300,
        "cognito:groups": ["leadintel-analyst"],
    }
    body.update(claims)
    return jwt.encode(body, key, algorithm="RS256")


def _verifier(key: rsa.RSAPrivateKey) -> CognitoJwtVerifier:
    return CognitoJwtVerifier(
        region="us-east-1",
        user_pool_id="pool",
        app_client_id="client",
        key_source=_StaticKeys(key.public_key()),
    )


def test_jwt_accepts_valid_access_token(rsa_key: rsa.RSAPrivateKey) -> None:
    claims = _verifier(rsa_key).verify(_token(rsa_key))
    assert claims["sub"] == "user-1"


@pytest.mark.parametrize(
    "claims",
    [
        {"token_use": "id"},
        {"client_id": "someone-else"},
        {"iss": "https://evil.example"},
        {"exp": 1},
    ],
)
def test_jwt_rejects_bad_tokens(rsa_key: rsa.RSAPrivateKey, claims: dict[str, object]) -> None:
    with pytest.raises(AuthenticationError):
        _verifier(rsa_key).verify(_token(rsa_key, **claims))


def test_jwt_rejects_wrong_signature(rsa_key: rsa.RSAPrivateKey) -> None:
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(AuthenticationError):
        _verifier(rsa_key).verify(_token(other))


# --- secrets & settings ------------------------------------------------------------------


@mock_aws
def test_secrets_manager_provider_caches_and_reads_json_keys() -> None:
    client = boto3.client("secretsmanager", region_name="us-east-1")
    arn = client.create_secret(Name="leadintel/test/db", SecretString='{"password":"pw"}')["ARN"]
    clock = [0.0]
    provider = AwsSecretsManagerProvider(client, ttl_s=10, clock=lambda: clock[0])
    assert provider.get(f"{arn}#password") == "pw"
    client.put_secret_value(SecretId=arn, SecretString='{"password":"rotated"}')
    assert provider.get(f"{arn}#password") == "pw"  # served from cache
    clock[0] = 11
    assert provider.get(f"{arn}#password") == "rotated"
    with pytest.raises(ConfigurationError):
        provider.get(f"{arn}#missing")


def test_settings_guardrails() -> None:
    with pytest.raises(ValueError, match="local-dev"):
        Settings(env="prod", auth_mode="local-dev")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="inline crypto keys"):
        Settings(env="dev", local_master_key_b64="AAAA")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="pii_kms_key_id"):
        Settings(env="dev")  # type: ignore[arg-type]
    ok = Settings(env="dev", pii_kms_key_id="k", blind_index_secret_arn="arn")  # type: ignore[arg-type]
    assert not ok.is_local
