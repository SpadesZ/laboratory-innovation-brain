"""The container deployment's database roles, as `compose.yaml` wires them. No database needed.

Every rule the research records keep is a trigger or a constraint, and a superuser or a table's
owner can step past both. So only `init` is the migrator; `web` and `local-models` connect as the
services' role, and never mount the migrator's password. `init` creates that role and grants it
row privileges only, after the migrations and before the operator's bootstrap. The roles and
grants themselves are exercised against a real server in
`tests/integration/test_service_roles_postgres.py` and `test_least_privilege_postgres.py`.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DOCKER = ROOT / "deployment" / "docker"
MIGRATOR_SECRETS = "/run/lab-brain-secrets"
SERVICE_SECRETS = "/run/lab-brain-app-secrets"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, DOCKER / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _services() -> dict[str, Any]:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    return compose["services"]  # type: ignore[no-any-return]


def _mounts(service: dict[str, Any]) -> dict[str, str]:
    """Volume name -> mount path, for the named volumes a service mounts."""
    found = {}
    for entry in service.get("volumes", ()):
        source, target = entry.split(":")[:2]
        if not source.startswith(("$", ".", "/")):
            found[source] = target
    return found


def test_only_init_holds_the_migrators_password():
    services = _services()
    holders = {name for name, s in services.items() if "secrets" in _mounts(s)}
    assert holders == {"secrets", "db", "init"}
    init = services["init"]["environment"]
    assert init["LAB_BRAIN_DATABASE_USER"] == "lab_brain"
    assert init["LAB_BRAIN_DATABASE_PASSWORD_FILE"] == f"{MIGRATOR_SECRETS}/db_password"
    assert init["LAB_BRAIN_APP_PASSWORD_FILE"] == f"{SERVICE_SECRETS}/db_password"


@pytest.mark.parametrize("name", ["web", "local-models"])
def test_the_services_connect_as_the_services_role(name):
    service = _services()[name]
    environment = service["environment"]
    assert environment["LAB_BRAIN_DATABASE_USER"] == "lab_brain_app"
    assert environment["LAB_BRAIN_DATABASE_PASSWORD_FILE"] == f"{SERVICE_SECRETS}/db_password"
    assert _mounts(service).get("app-secrets") == SERVICE_SECRETS
    assert any(v.startswith("app-secrets:") and v.endswith(":ro") for v in service["volumes"])


def test_the_first_start_generates_both_passwords_and_the_database_stays_internal():
    services = _services()
    assert services["secrets"]["command"] == [
        f"{MIGRATOR_SECRETS}/db_password",
        f"{SERVICE_SECRETS}/db_password",
    ]
    assert "ports" not in services["db"]


def test_init_creates_and_grants_the_roles_after_the_migrations_and_before_the_bootstrap():
    steps = [
        line
        for line in (DOCKER / "bootstrap.sh").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith(("#", " ", "set ", "if ", "fi"))
    ]
    assert steps[:4] == [
        "python /app/scripts/migrate.py",
        'python /app/deployment/docker/service_roles.py "$LAB_BRAIN_APP_PASSWORD_FILE"',
        "lab-brain admin db-roles --app-role lab_brain_app --reader-role lab_brain_reader",
        'lab-brain admin actor "$LAB_BRAIN_ACTOR" --name "$LAB_BRAIN_ACTOR_NAME"',
    ]


def test_each_password_is_generated_once_and_kept(tmp_path):
    make_secret = _load("make_secret")
    first, second = tmp_path / "a" / "db_password", tmp_path / "b" / "db_password"
    assert make_secret.main([str(first), str(second)]) == 0
    kept = first.read_text(encoding="ascii")
    assert len(kept) == 48 and kept != second.read_text(encoding="ascii")
    assert make_secret.ensure_secret(str(first)).endswith(": kept")
    assert first.read_text(encoding="ascii") == kept


def test_the_role_password_is_sent_as_a_verifier_that_checks_only_its_password():
    roles = _load("service_roles")
    password = "0123456789abcdef" * 3
    stored = roles.scram_verifier(password)
    assert stored.startswith("SCRAM-SHA-256$4096:") and password not in stored
    assert roles.verifies(stored, password)
    assert not roles.verifies(stored, password[:-1] + "0")
    assert roles.scram_verifier(password, salt=b"s" * 16) == roles.scram_verifier(
        password, salt=b"s" * 16
    )
    assert roles.scram_verifier(password) != stored, "a fresh salt each time"
    for malformed in (None, "", "md5abc", "SCRAM-SHA-256$x", "SCRAM-SHA-256$4096:!!$a:b"):
        assert not roles.verifies(malformed, password)


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
@pytest.mark.parametrize(
    ("user", "expected"),
    [(None, "lab_brain"), ("", "lab_brain"), ("lab_brain_app", "lab_brain_app"), ("x;y", None)],
)
def test_the_entrypoint_connects_as_the_named_role_only(tmp_path, user, expected):
    secret = tmp_path / "db_password"
    secret.write_text("p" * 48, encoding="ascii")
    env = {k: v for k, v in os.environ.items() if not k.startswith("LAB_BRAIN_")} | {
        "LAB_BRAIN_DATABASE_PASSWORD_FILE": str(secret)
    }
    if user is not None:
        env["LAB_BRAIN_DATABASE_USER"] = user
    result = subprocess.run(
        ["sh", str(DOCKER / "entrypoint.sh"), "sh", "-c", 'printf %s "$LAB_BRAIN_DATABASE_URL"'],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if expected is None:
        assert result.returncode == 2 and "plain lower-case role name" in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert result.stdout == f"postgresql://{expected}:{'p' * 48}@db:5432/lab_brain"


def test_the_workspace_runs_with_accounts_and_mail_is_optional():
    """The deployment signs each person in (`--accounts`); mail is an optional env file, and the
    outbox is a volume of the workspace's own."""
    web = _services()["web"]
    command = " ".join(web["command"])
    assert "lab-brain web --accounts" in command and "--actor" not in command
    assert {"path": "deployment/docker/mail.env", "required": False} in web["env_file"]
    assert _mounts(web).get("mail-outbox") == "/var/lib/lab-brain/outbox"
