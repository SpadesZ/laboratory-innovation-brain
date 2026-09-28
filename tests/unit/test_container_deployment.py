"""The container deployment's rules that need no database.

The workspace has no login: whoever reaches it acts as its actor. So it listens on loopback -- and
in a container, where loopback is the container's own, on the container's interface, which the
deployment publishes on the HOST's loopback only (`compose.yaml`). `--in-container` is refused
anywhere a container runtime has not marked the process, so it cannot be used to listen on a real
machine's network. The Host a browser must name stays the loopback one, and `host.docker.internal`
is this machine only where the container deployment says so.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest

from lab_brain.interfaces import cli
from lab_brain.interfaces.config import ConfigurationError, Settings
from lab_brain.interfaces.web import Workspace, allowed_hosts, listen_address
from lab_brain.llm_runtime.provider import is_this_machine_url
from lab_brain.research.vertical import load_vertical_factory
from tests.wsgi_client import Browser


def test_the_workspace_listens_on_loopback_or_inside_a_marked_container_only(tmp_path: Path):
    none = (tmp_path / "absent",)
    marker = tmp_path / ".dockerenv"
    marker.write_text("")
    assert listen_address("127.0.0.1", container=False, markers=none) == "127.0.0.1"
    with pytest.raises(ConfigurationError, match="serves this machine only"):
        listen_address("0.0.0.0", container=False, markers=(marker,))
    with pytest.raises(ConfigurationError, match="not running in a container"):
        listen_address("0.0.0.0", container=True, markers=none)
    assert listen_address("0.0.0.0", container=True, markers=(marker,)) == "0.0.0.0"
    with pytest.raises(ConfigurationError, match=r"listens on 0.0.0.0"):
        listen_address("192.168.1.10", container=True, markers=(marker,))


def test_the_docker_host_is_this_machine_only_where_the_deployment_says_so():
    gateway = frozenset({"host.docker.internal"})
    assert not is_this_machine_url("http://host.docker.internal:11434/v1")
    assert is_this_machine_url("http://host.docker.internal:11434/v1", gateway)
    assert not is_this_machine_url("http://host.docker.internal.evil.test/v1", gateway)
    assert not is_this_machine_url("http://10.0.0.5:11434/v1", gateway)
    assert is_this_machine_url("http://127.0.0.1:11434/v1")


class _Connection:
    def __init__(self) -> None:
        self.closed = False

    def execute(self, sql: str, params: Any = None) -> Any:
        assert sql == "SELECT 1"
        return self

    def fetchone(self) -> tuple[int]:
        return (1,)

    def close(self) -> None:
        self.closed = True


def _main(*argv: str) -> tuple[int, str]:
    out = io.StringIO()
    code = cli.main(
        list(argv),
        out=out,
        env={"LAB_BRAIN_DATABASE_URL": "postgresql://unused"},
        connect=lambda s: _Connection(),
    )
    return code, out.getvalue()


def test_the_command_line_refuses_the_container_flags_outside_a_container(tmp_path: Path):
    code, said = _main(
        "web",
        "--actor",
        "act:x",
        "--artifact-root",
        str(tmp_path),
        "--host-gateway",
        "host.docker.internal",
    )
    assert code == 2 and "applies only with --in-container" in said
    if Path("/.dockerenv").exists() or Path("/run/.containerenv").exists():  # pragma: no cover
        pytest.skip("this test process runs in a container")
    code, said = _main(
        "web",
        "--actor",
        "act:x",
        "--artifact-root",
        str(tmp_path),
        "--host",
        "0.0.0.0",
        "--in-container",
    )
    assert code == 2 and "not running in a container" in said


def test_the_health_check_answers_for_an_allowed_host_only(tmp_path: Path):
    opened: list[_Connection] = []

    def connect(settings: Settings) -> _Connection:
        opened.append(_Connection())
        return opened[-1]

    workspace = Workspace(
        actor_id="act:x",
        settings=Settings(dsn="postgresql://unused"),
        connect=connect,
        artifact_root=tmp_path,
        vertical_factory=load_vertical_factory("silicon_photonics"),
        allowed_hosts=allowed_hosts("127.0.0.1", 8765),
    )
    browser = Browser(workspace, host="localhost:8765")
    answer = browser.get("/healthz")
    assert (answer.status, answer.text) == (200, "ok")
    assert opened and all(c.closed for c in opened)
    assert browser.get("/healthz", host="lab-brain:8765").status == 400
