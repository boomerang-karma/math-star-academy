"""Safety rails of the AWS setup/teardown scripts, exercised with a fake ``aws``/``npx`` on PATH.

The fake CLI records every invocation, so the tests can prove that refusals and
dry runs never issue a mutating call.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MUTATING = (
    "create-db-cluster-snapshot",
    "delete-objects",
    "modify-db-cluster",
    "delete-secret",
    "put-secret-value",
    "update-user-pool",
    "destroy",
    "deploy",
)

FAKE_AWS = r"""#!/usr/bin/env bash
echo "aws $*" >> "$STUB_LOG"
case "$*" in
  "sts get-caller-identity"*) echo "${STUB_ACCOUNT:-111111111111}" ;;
  *"describe-stacks --stack-name leadintel-dev-data"*)
     case "$*" in
       *ClusterIdentifier*) echo "leadintel-dev-cluster" ;;
       *RawBucketName*) echo "leadintel-dev-raw" ;;
       *AuditBucketName*) echo "leadintel-dev-audit" ;;
       *) echo "None" ;;
     esac ;;
  *"describe-stacks"*) echo "None" ;;
  *"s3api head-bucket"*) exit 0 ;;
  *"s3api list-object-versions"*)
     echo '{"Versions":[{"Key":"a","VersionId":"1"}],"DeleteMarkers":[]}' ;;
  *"list-secrets"*) echo "" ;;
  *"describe-db-cluster-snapshots"*) echo "" ;;
  *"list-buckets"*) echo "" ;;
  *) echo "" ;;
esac
"""

FAKE_NPX = r"""#!/usr/bin/env bash
echo "npx $*" >> "$STUB_LOG"
"""


@pytest.fixture
def fake_cli(tmp_path: Path) -> dict[str, str]:
    if shutil.which("jq") is None:
        pytest.skip("jq is required by the scripts")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("aws", FAKE_AWS), ("npx", FAKE_NPX)):
        path = bin_dir / name
        path.write_text(body)
        path.chmod(0o755)
    log = tmp_path / "calls.log"
    log.touch()
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    env.update({"PATH": f"{bin_dir}:{os.environ['PATH']}", "STUB_LOG": str(log)})
    return env


def run(
    script: str, *args: str, env: dict[str, str], stdin: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(ROOT / script), *args],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )


def calls(env: dict[str, str]) -> str:
    return Path(env["STUB_LOG"]).read_text()


def assert_no_mutation(env: dict[str, str]) -> None:
    log = calls(env)
    for verb in MUTATING:
        assert f" {verb}" not in log, f"unexpected mutating call '{verb}':\n{log}"


def test_dry_run_teardown_plans_but_changes_nothing(fake_cli: dict[str, str]) -> None:
    result = run("scripts/aws/teardown.sh", "--env", "dev", "--dry-run", env=fake_cli)
    assert result.returncode == 0, result.stderr
    assert (
        "[dry-run] aws rds create-db-cluster-snapshot --db-cluster-identifier leadintel-dev-cluster"
        in result.stderr
    )
    assert "[dry-run] delete 1 object versions from leadintel-dev-raw" in result.stderr
    assert "[dry-run] cdk destroy --all -c env=dev --force" in result.stderr
    assert_no_mutation(fake_cli)


def test_teardown_requires_typed_confirmation(fake_cli: dict[str, str]) -> None:
    result = run("scripts/aws/teardown.sh", "--env", "dev", env=fake_cli, stdin="yes\n")
    assert result.returncode != 0
    assert "confirmation did not match" in result.stderr
    assert_no_mutation(fake_cli)


def test_protected_environment_needs_explicit_flag(fake_cli: dict[str, str]) -> None:
    env = {**fake_cli, "STUB_ACCOUNT": "000000000000"}  # the account pinned in config/prod.json
    result = run("scripts/aws/teardown.sh", "--env", "prod", "--dry-run", env=env)
    assert result.returncode != 0
    assert "--i-understand-this-destroys-prod" in result.stderr
    refused = run(
        "scripts/aws/teardown.sh",
        "--env",
        "prod",
        "--i-understand-this-destroys-prod",
        "--skip-snapshot",
        "--dry-run",
        env=env,
    )
    assert refused.returncode != 0
    assert "final snapshot is mandatory" in refused.stderr
    assert_no_mutation(env)


def test_wrong_account_is_refused(fake_cli: dict[str, str]) -> None:
    result = run(
        "scripts/aws/teardown.sh",
        "--env",
        "prod",
        "--i-understand-this-destroys-prod",
        "--dry-run",
        env=fake_cli,
    )  # credentials for 111111111111, config pins 000000000000
    assert result.returncode != 0
    assert "pins account 000000000000" in result.stderr
    assert_no_mutation(fake_cli)


def test_setup_refuses_placeholder_cognito_domain(fake_cli: dict[str, str]) -> None:
    for tool in ("node", "uv"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} not installed")
    result = run("scripts/aws/setup.sh", "--env", "dev", env=fake_cli)
    assert result.returncode != 0
    assert "globally unique cognito_domain_prefix" in result.stderr
    assert_no_mutation(fake_cli)


def test_blind_index_rotation_is_refused(fake_cli: dict[str, str]) -> None:
    if shutil.which("openssl") is None:
        pytest.skip("openssl not installed")
    result = run(
        "scripts/aws/rotate-secrets.sh", "--env", "dev", "--what", "blind-index", env=fake_cli
    )
    assert result.returncode != 0
    assert "re-index" in result.stderr
    assert_no_mutation(fake_cli)


def test_help_texts(fake_cli: dict[str, str]) -> None:
    for script in (
        "scripts/aws/setup.sh",
        "scripts/aws/teardown.sh",
        "scripts/aws/bootstrap.sh",
        "scripts/aws/status.sh",
        "scripts/aws/rotate-secrets.sh",
    ):
        result = run(script, "--help", env=fake_cli)
        assert result.returncode == 0
        assert "--env" in result.stdout
