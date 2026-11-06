"""Requests to a vendor's service, with the standard library only: a JSON body or a multipart form, one page per
request, the answer as JSON. A vendor's service runs on loopback, so no proxy applies."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ServiceError(RuntimeError):
    """A request the service did not answer with 200 and a JSON object (the page's error)."""


def get(url: str, timeout: float = 10.0) -> int:
    """The status of ``GET url`` (0 when nothing answers)."""
    try:
        with _OPENER.open(urllib.request.Request(url), timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except OSError:
        return 0


def _send(request: urllib.request.Request, timeout: float) -> dict:
    try:
        with _OPENER.open(request, timeout=timeout) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        raise ServiceError(f"{request.full_url}: HTTP {e.code}: {e.read()[:500]!r}") from None
    try:
        body = json.loads(data)
    except ValueError:
        raise ServiceError(f"{request.full_url}: not JSON: {data[:200]!r}") from None
    if not isinstance(body, dict):
        raise ServiceError(f"{request.full_url}: a JSON {type(body).__name__}, not an object")
    return body


def post_json(url: str, body: dict, timeout: float) -> dict:
    """``POST url`` with ``body`` as JSON; the answer's JSON object."""
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
    return _send(request, timeout)


def multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    """A ``multipart/form-data`` body and its content type: the fields first (a list value is one field per item,
    as httpx sends it), then the files (``name -> (filename, bytes, content type)``)."""
    boundary = uuid.uuid4().hex
    out = []
    for name, value in fields.items():
        for item in value if isinstance(value, (list, tuple)) else [value]:
            out.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{item}\r\n'.encode())
    for name, (filename, data, kind) in files.items():
        out.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                   f"Content-Type: {kind}\r\n\r\n".encode() + data + b"\r\n")
    out.append(f"--{boundary}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={boundary}"


def post_form(url: str, fields: dict, files: dict, timeout: float) -> dict:
    """``POST url`` with a multipart form (``multipart``); the answer's JSON object."""
    data, kind = multipart(fields, files)
    request = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": kind})
    return _send(request, timeout)
