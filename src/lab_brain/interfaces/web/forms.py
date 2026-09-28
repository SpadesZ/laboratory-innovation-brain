"""Request bodies: `multipart/form-data` (uploads) and `application/x-www-form-urlencoded`.

Standard library only (`email` parses MIME multipart exactly as the web sends it). The body is
read only up to a declared limit and refused beyond it, before any of it is parsed.
"""

from __future__ import annotations

import email.parser
import email.policy
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs


class FormError(ValueError):
    """The request body is not a form this workspace accepts."""


@dataclass(frozen=True)
class Upload:
    filename: str
    data: bytes


@dataclass(frozen=True)
class Form:
    fields: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    files: Mapping[str, tuple[Upload, ...]] = field(default_factory=dict)

    def value(self, name: str) -> str:
        """The single text value of `name`, stripped; empty when absent."""
        values = self.fields.get(name, ())
        return values[0].strip() if values else ""

    def uploads(self, name: str) -> tuple[Upload, ...]:
        """Uploaded files under `name`; a browser sends an empty part for an unused input."""
        return tuple(u for u in self.files.get(name, ()) if u.filename or u.data)


def read_form(environ: Mapping[str, Any], *, limit: int) -> Form:
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError as exc:
        raise FormError("the request declares no readable length") from exc
    if length < 0 or length > limit:
        raise FormError(f"the request body is {length} bytes; this workspace accepts {limit}")
    body = environ["wsgi.input"].read(length) if length else b""
    content_type = str(environ.get("CONTENT_TYPE") or "")
    if content_type.startswith("multipart/form-data"):
        return _multipart(content_type, body)
    if content_type.startswith("application/x-www-form-urlencoded") or not body:
        parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True, strict_parsing=False)
        return Form(fields={k: tuple(v) for k, v in parsed.items()})
    raise FormError(f"unsupported request body {content_type!r}")


def _multipart(content_type: str, body: bytes) -> Form:
    message = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
        b"Content-Type: " + content_type.encode("latin-1") + b"\r\n\r\n" + body
    )
    if not message.is_multipart():
        raise FormError("the multipart body could not be read")
    fields: dict[str, list[str]] = {}
    files: dict[str, list[Upload]] = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not isinstance(name, str) or not name:
            raise FormError("a form part has no name")
        payload = part.get_payload(decode=True)
        data = payload if isinstance(payload, bytes) else b""
        filename = part.get_filename()
        if filename is None:
            charset = part.get_content_charset() or "utf-8"
            fields.setdefault(name, []).append(data.decode(charset))
        else:
            # Only the file's own name, never a path a browser may prepend.
            base = filename.replace("\\", "/").rsplit("/", 1)[-1]
            files.setdefault(name, []).append(Upload(filename=base, data=data))
    return Form(
        fields={k: tuple(v) for k, v in fields.items()},
        files={k: tuple(v) for k, v in files.items()},
    )


__all__ = ["Form", "FormError", "Upload", "read_form"]
