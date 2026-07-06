"""Small HTTP helpers for public source tools."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class SourceHttpError(RuntimeError):
    """Raised when a public source HTTP request fails."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        payload: Any | None = None,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.payload = payload
        self.headers = headers or {}


@dataclass(frozen=True)
class JsonHttpResponse:
    """Decoded JSON response with selected HTTP metadata."""

    payload: Any
    status_code: int
    headers: dict[str, str]
    url: str


@dataclass(frozen=True)
class TextHttpResponse:
    """Text response with selected HTTP metadata."""

    text: str
    status_code: int
    headers: dict[str, str]
    url: str


class JsonHttpClient:
    """Minimal JSON HTTP client used by source tools."""

    def get_json(
        self,
        url: str,
        *,
        query_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout_seconds: int = 20,
    ) -> JsonHttpResponse:
        final_url = self._url_with_query(url, query_params or {})
        request = Request(final_url, headers=headers or {}, method="GET")
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                body = response.read()
                status_code = int(response.status)
                response_headers = dict(response.headers.items())
        except HTTPError as exc:
            body = exc.read()
            payload = self._decode_error_payload(body)
            raise SourceHttpError(
                self._error_message(exc.code, payload),
                status_code=exc.code,
                retryable=exc.code in {408, 429, 500, 502, 503, 504},
                payload=payload,
                headers=dict(exc.headers.items()) if exc.headers else {},
            ) from exc
        except URLError as exc:
            raise SourceHttpError(
                str(exc.reason),
                retryable=True,
            ) from exc
        except TimeoutError as exc:
            raise SourceHttpError("request timed out", retryable=True) from exc

        payload = self._decode_json(body)
        return JsonHttpResponse(
            payload=payload,
            status_code=status_code,
            headers=response_headers,
            url=final_url,
        )

    def get_text(
        self,
        url: str,
        *,
        query_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout_seconds: int = 20,
    ) -> TextHttpResponse:
        final_url = self._url_with_query(url, query_params or {})
        request = Request(final_url, headers=headers or {}, method="GET")
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                body = response.read()
                status_code = int(response.status)
                response_headers = dict(response.headers.items())
        except HTTPError as exc:
            body = exc.read()
            payload = self._decode_error_payload(body)
            raise SourceHttpError(
                self._error_message(exc.code, payload),
                status_code=exc.code,
                retryable=exc.code in {408, 429, 500, 502, 503, 504},
                payload=payload,
                headers=dict(exc.headers.items()) if exc.headers else {},
            ) from exc
        except URLError as exc:
            raise SourceHttpError(
                str(exc.reason),
                retryable=True,
            ) from exc
        except TimeoutError as exc:
            raise SourceHttpError("request timed out", retryable=True) from exc

        return TextHttpResponse(
            text=body.decode("utf-8", errors="replace"),
            status_code=status_code,
            headers=response_headers,
            url=final_url,
        )

    @staticmethod
    def _url_with_query(url: str, query_params: dict[str, Any]) -> str:
        if not query_params:
            return url
        encoded = urlencode(
            {
                key: value
                for key, value in query_params.items()
                if value is not None and value != ""
            },
            doseq=True,
        )
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}{encoded}" if encoded else url

    @staticmethod
    def _decode_json(body: bytes) -> Any:
        if not body:
            return None
        try:
            return json.loads(body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise SourceHttpError("response did not contain valid JSON", retryable=False) from exc

    @staticmethod
    def _decode_error_payload(body: bytes) -> Any:
        if not body:
            return None
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return {"body": body.decode("utf-8", errors="replace")[:500]}

    @staticmethod
    def _error_message(status_code: int, payload: Any) -> str:
        if isinstance(payload, dict):
            message = payload.get("message") or payload.get("error")
            if message:
                return str(message)
        return f"HTTP request failed with status {status_code}"


def selected_rate_limit(headers: dict[str, str], *, prefix: str) -> dict[str, str]:
    """Extract source-specific rate-limit headers in a stable metadata shape."""

    normalized_prefix = prefix.lower()
    return {
        key.lower(): value
        for key, value in headers.items()
        if key.lower().startswith(normalized_prefix)
    }
