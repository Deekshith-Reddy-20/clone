"""Official Outpero Lead Intake HTTP client.

Documented endpoints (https://outpero.com / api.outpero.com):
  POST /lead-intake/{slug}
  GET  /lead-intake/{slug}/schema
  GET  /lead-intake/{slug}/calls/{call_id}
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class OutperoApiError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        body: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.body = body


class OutperoClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.outpero_api_base_url).rstrip("/")
        self.timeout = timeout_seconds
        self.max_retries = max_retries

    def _headers(self, lead_secret: str) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Outpero-Lead-Secret": lead_secret,
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        lead_secret: str,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.request(
                        method,
                        url,
                        headers=self._headers(lead_secret),
                        json=json_body,
                    )
            except httpx.TimeoutException as exc:
                last_error = OutperoApiError("Outpero request timed out", retryable=True)
                logger.warning("outpero_timeout path=%s attempt=%s", path, attempt)
                if attempt >= self.max_retries:
                    raise last_error from exc
                time.sleep(min(2**attempt, 8))
                continue
            except httpx.HTTPError as exc:
                last_error = OutperoApiError(f"Outpero transport error: {exc}", retryable=True)
                logger.warning("outpero_transport path=%s err=%s", path, exc)
                if attempt >= self.max_retries:
                    raise last_error from exc
                time.sleep(min(2**attempt, 8))
                continue

            if response.status_code in (429, 500, 502, 503, 504):
                retryable = True
                last_error = OutperoApiError(
                    f"Outpero HTTP {response.status_code}",
                    status_code=response.status_code,
                    retryable=retryable,
                    body=_safe_json(response),
                )
                logger.warning(
                    "outpero_retryable status=%s path=%s attempt=%s",
                    response.status_code,
                    path,
                    attempt,
                )
                if attempt >= self.max_retries:
                    raise last_error
                # Honor Retry-After when present
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else min(2**attempt, 8)
                except ValueError:
                    delay = min(2**attempt, 8)
                time.sleep(delay)
                continue

            if response.status_code >= 400:
                body = _safe_json(response)
                message = _error_message(body) or f"Outpero HTTP {response.status_code}"
                raise OutperoApiError(
                    message,
                    status_code=response.status_code,
                    retryable=False,
                    body=body,
                )

            if response.status_code == 204 or not response.content:
                return {}
            return _safe_json(response)

        if last_error:
            raise last_error
        raise OutperoApiError("Outpero request failed")

    def get_schema(self, *, slug: str, lead_secret: str) -> dict[str, Any]:
        data = self._request("GET", f"/lead-intake/{slug}/schema", lead_secret=lead_secret)
        return data if isinstance(data, dict) else {"raw": data}

    def submit_lead(
        self,
        *,
        slug: str,
        lead_secret: str,
        phone: str,
        pre_call: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"phone": phone}
        if pre_call:
            for key, value in pre_call.items():
                if key == "phone" or value is None:
                    continue
                body[key] = value
        data = self._request(
            "POST",
            f"/lead-intake/{slug}",
            lead_secret=lead_secret,
            json_body=body,
        )
        return data if isinstance(data, dict) else {"raw": data}

    def get_call(
        self,
        *,
        slug: str,
        lead_secret: str,
        call_id: str,
    ) -> dict[str, Any]:
        data = self._request(
            "GET",
            f"/lead-intake/{slug}/calls/{call_id}",
            lead_secret=lead_secret,
        )
        return data if isinstance(data, dict) else {"raw": data}


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        text = (response.text or "")[:500]
        return {"text": text}


def _error_message(body: Any) -> str | None:
    if isinstance(body, dict):
        for key in ("message", "error", "detail"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None
