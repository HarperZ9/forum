from __future__ import annotations

import dataclasses
import json
from typing import Any

MAX_BODY = 1 << 20  # 1 MiB cap on a request body

_REASONS = {
    200: "OK",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    408: "Request Timeout",
    413: "Payload Too Large",
    500: "Internal Server Error",
    502: "Bad Gateway",
}


@dataclasses.dataclass(frozen=True, slots=True)
class Response:
    status: int
    body: bytes
    content_type: str = "application/json"

    @property
    def reason(self) -> str:
        return _REASONS.get(self.status, "Unknown")


def json_response(obj: Any, status: int = 200) -> Response:
    return Response(status, json.dumps(obj).encode("utf-8"))


def error(status: int, message: str) -> Response:
    return json_response({"error": message}, status)
