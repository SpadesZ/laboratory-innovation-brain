"""Endpoints for the transport tests: real sockets on 127.0.0.1, plain or TLS, that either answer
as an OpenAI-compatible provider or redirect -- and record every request they receive, with its
Authorization header and body, so a test can show what reached them and what did not.

The TLS endpoints use a throwaway certificate authority made for the test session with the
`openssl` command (`make_tls`). The client under test trusts it through `SSL_CERT_FILE`, which is
how the standard library's default context finds extra roots -- the client itself is not changed
or configured for the test.
"""

from __future__ import annotations

import json
import shutil
import ssl
import subprocess
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

#: What a redirecting endpoint says in its body: a test shows none of it is kept.
REDIRECT_BODY = "this service moved; follow me"


@dataclass(frozen=True)
class Seen:
    method: str
    path: str
    authorization: str | None
    body: bytes


@dataclass(frozen=True)
class TLS:
    ca: Path
    cert: Path
    key: Path

    def server_context(self) -> ssl.SSLContext:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.cert, self.key)
        return context


def make_tls(directory: Path) -> TLS | None:
    """A CA and a server certificate for 127.0.0.1 and localhost, or None without `openssl`."""
    openssl = shutil.which("openssl")
    if openssl is None:
        return None

    def run(*args: str) -> None:
        subprocess.run([openssl, *args], cwd=directory, check=True, capture_output=True)

    run(
        "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
        "-keyout", "ca.key", "-out", "ca.pem", "-subj", "/CN=lab-brain transport test CA",
        "-addext", "basicConstraints=critical,CA:TRUE",
        "-addext", "keyUsage=critical,keyCertSign,cRLSign",
    )  # fmt: skip
    run(
        "req", "-newkey", "rsa:2048", "-nodes",
        "-keyout", "server.key", "-out", "server.csr", "-subj", "/CN=127.0.0.1",
    )  # fmt: skip
    (directory / "server.ext").write_text(
        "subjectAltName=IP:127.0.0.1,DNS:localhost\n"
        "basicConstraints=CA:FALSE\n"
        "keyUsage=critical,digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth\n"
        "authorityKeyIdentifier=keyid\n"
        "subjectKeyIdentifier=hash\n",
        encoding="ascii",
    )
    run(
        "x509", "-req", "-in", "server.csr", "-CA", "ca.pem", "-CAkey", "ca.key",
        "-set_serial", "2", "-days", "2", "-out", "server.pem", "-extfile", "server.ext",
    )  # fmt: skip
    return TLS(directory / "ca.pem", directory / "server.pem", directory / "server.key")


@dataclass
class Endpoint:
    """`redirect`: None answers as a provider (model `m`, reply `ok`); else (status, location),
    where `{path}` in the location is replaced by the request's path. `host` is the name the URL
    uses for it -- `localhost` makes the same socket a different origin from `127.0.0.1`."""

    tls: TLS | None = None
    host: str = "127.0.0.1"
    redirect: tuple[int, str] | None = None
    seen: list[Seen] = field(default_factory=list)
    port: int = 0
    _server: ThreadingHTTPServer | None = None

    @property
    def origin(self) -> str:
        return f"{'https' if self.tls else 'http'}://{self.host}:{self.port}"

    def start(self) -> Endpoint:
        endpoint = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                return

            def _handle(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                endpoint.seen.append(
                    Seen(self.command, self.path, self.headers.get("Authorization"), body)
                )
                if endpoint.redirect is not None:
                    status, location = endpoint.redirect
                    raw = REDIRECT_BODY.encode()
                    self.send_response(status)
                    self.send_header("Location", location.replace("{path}", self.path))
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                if self.path.endswith("/models"):
                    answer: object = {"object": "list", "data": [{"id": "m"}]}
                else:
                    answer = {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
                raw = json.dumps(answer).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:
                self._handle()

            def do_POST(self) -> None:
                self._handle()

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        if self.tls is not None:
            server.socket = self.tls.server_context().wrap_socket(server.socket, server_side=True)
        self._server = server
        self.port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


__all__ = ["REDIRECT_BODY", "TLS", "Endpoint", "Seen", "make_tls"]
