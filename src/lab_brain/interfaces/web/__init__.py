"""The research workspace: the product vertical in a browser (`lab-brain web`).

`app.Workspace` is the WSGI application; `serve` runs it on this machine's loopback interface with
the standard library's server. See `app` for what it does and, as importantly, what it does not.
"""

from __future__ import annotations

import socketserver
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from lab_brain.interfaces.config import ConfigurationError
from lab_brain.interfaces.web.app import LOOPBACK, Workspace, allowed_hosts

#: Files a container runtime places in every container (Docker, Podman). Their absence means the
#: process is not in a container, whatever it was told.
CONTAINER_MARKERS = (Path("/.dockerenv"), Path("/run/.containerenv"))


def in_container(markers: tuple[Path, ...] = CONTAINER_MARKERS) -> bool:
    return any(m.exists() for m in markers)


def listen_address(
    host: str, *, container: bool, markers: tuple[Path, ...] = CONTAINER_MARKERS
) -> str:
    """Where the workspace may listen. Loopback, always -- except inside a container, where it
    listens on the container's own interface and the deployment publishes that port on the
    HOST's loopback only (compose.yaml). Asked for anything else, it refuses: the workspace has no
    login, and anyone who could reach it would act as its actor."""
    if container:
        if not in_container(markers):
            raise ConfigurationError(
                "--in-container was given, but this process is not running in a container: "
                "outside one the workspace serves this machine's loopback interface only"
            )
        if host not in ("0.0.0.0", "::"):
            raise ConfigurationError("in a container the workspace listens on 0.0.0.0")
        return host
    if host not in LOOPBACK and host != "::1":
        raise ConfigurationError(
            f"the research workspace serves this machine only (127.0.0.1 or localhost), not "
            f"{host!r}: it has no login, and anyone who could reach it would act as its actor"
        )
    return host


class _ThreadingServer(socketserver.ThreadingMixIn, WSGIServer):
    """One thread per request, so a page can load while a research run is working."""

    daemon_threads = True


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature
        return


def serve(  # pragma: no cover - blocks
    workspace: Workspace, *, host: str, port: int, container: bool = False
) -> None:
    """Serve until interrupted, where `listen_address` allows."""
    host = listen_address(host, container=container)
    with make_server(
        host, port, workspace, server_class=_ThreadingServer, handler_class=_QuietHandler
    ) as server:
        server.serve_forever()


__all__ = ["Workspace", "allowed_hosts", "in_container", "listen_address", "serve"]
