"""A browser's requests, delivered to a WSGI application in-process.

What a browser sends -- a Host header, forms encoded as `multipart/form-data` or urlencoded, an
Origin on a POST -- built by hand so the tests exercise the same parsing a real browser's request
goes through, without a socket.
"""

from __future__ import annotations

import io
import secrets
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlencode, urlsplit

WSGIApp = Callable[[dict[str, Any], Callable[..., Any]], Iterable[bytes]]


@dataclass(frozen=True)
class Reply:
    status: int
    headers: Mapping[str, str]
    body: bytes

    @property
    def text(self) -> str:
        return self.body.decode("utf-8")

    @property
    def location(self) -> str:
        return self.headers.get("Location", "")


class Browser:
    def __init__(self, app: WSGIApp, *, host: str = "127.0.0.1:8765") -> None:
        self._app = app
        self.host = host

    def get(self, url: str, *, host: str | None = None) -> Reply:
        return self._call("GET", url, b"", "", host=host)

    def post(
        self,
        url: str,
        fields: Mapping[str, str | Sequence[str]],
        files: Mapping[str, Sequence[tuple[str, bytes]]] | None = None,
        *,
        origin: str | None = "same",
        host: str | None = None,
    ) -> Reply:
        if files:
            body, content_type = _multipart(fields, files)
        else:
            body = urlencode(
                [(k, v) for k, vs in fields.items() for v in ([vs] if isinstance(vs, str) else vs)]
            ).encode()
            content_type = "application/x-www-form-urlencoded"
        return self._call("POST", url, body, content_type, host=host, origin=origin)

    def _call(
        self,
        method: str,
        url: str,
        body: bytes,
        content_type: str,
        *,
        host: str | None,
        origin: str | None = None,
    ) -> Reply:
        parts = urlsplit(url)
        environ: dict[str, Any] = {
            "REQUEST_METHOD": method,
            # Decoded, as a WSGI server hands it over (wsgiref: unquote as latin-1).
            "PATH_INFO": unquote(parts.path, encoding="latin-1"),
            "QUERY_STRING": parts.query,
            "SERVER_NAME": "127.0.0.1",
            "SERVER_PORT": "8765",
            "HTTP_HOST": host or self.host,
            "CONTENT_LENGTH": str(len(body)),
            "CONTENT_TYPE": content_type,
            "wsgi.input": io.BytesIO(body),
            "wsgi.url_scheme": "http",
            "wsgi.version": (1, 0),
            "wsgi.errors": io.StringIO(),
            "wsgi.multithread": False,
            "wsgi.multiprocess": False,
            "wsgi.run_once": False,
        }
        if origin is not None:
            environ["HTTP_ORIGIN"] = f"http://{host or self.host}" if origin == "same" else origin
        captured: dict[str, Any] = {}

        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            captured["status"] = int(status.split(" ", 1)[0])
            captured["headers"] = dict(headers)

        chunks = self._app(environ, start_response)
        return Reply(captured["status"], captured["headers"], b"".join(chunks))


def _multipart(
    fields: Mapping[str, str | Sequence[str]], files: Mapping[str, Sequence[tuple[str, bytes]]]
) -> tuple[bytes, str]:
    boundary = "----labbrain" + secrets.token_hex(8)
    out = io.BytesIO()
    for name, values in fields.items():
        for value in [values] if isinstance(values, str) else values:
            out.write(f"--{boundary}\r\n".encode())
            out.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
            out.write(value.encode("utf-8") + b"\r\n")
    for name, uploads in files.items():
        for filename, data in uploads:
            out.write(f"--{boundary}\r\n".encode())
            out.write(
                f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
            )
            out.write(b"Content-Type: application/octet-stream\r\n\r\n")
            out.write(data + b"\r\n")
    out.write(f"--{boundary}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={boundary}"


__all__ = ["Browser", "Reply"]
