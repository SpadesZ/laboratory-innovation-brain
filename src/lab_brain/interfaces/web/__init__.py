"""The research workspace: the product vertical in a browser (`lab-brain web`).

`app.Workspace` is the WSGI application; `serve` runs it on this machine's loopback interface with
the standard library's server. See `app` for what it does and, as importantly, what it does not.
"""

from __future__ import annotations

import socketserver
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from lab_brain.interfaces.config import ConfigurationError
from lab_brain.interfaces.web.app import LOOPBACK, Workspace, allowed_hosts


class _ThreadingServer(socketserver.ThreadingMixIn, WSGIServer):
    """One thread per request, so a page can load while a research run is working."""

    daemon_threads = True


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature
        return


def serve(workspace: Workspace, *, host: str, port: int) -> None:  # pragma: no cover - blocks
    """Serve until interrupted. Loopback only: the workspace has no login of its own."""
    if host not in LOOPBACK and host != "::1":
        raise ConfigurationError(
            f"the research workspace serves this machine only (127.0.0.1 or localhost), not "
            f"{host!r}: it has no login, and anyone who could reach it would act as its actor"
        )
    with make_server(
        host, port, workspace, server_class=_ThreadingServer, handler_class=_QuietHandler
    ) as server:
        server.serve_forever()


__all__ = ["Workspace", "allowed_hosts", "serve"]
