"""Postcode API client (NIPOST gateway, Lookup level 1) plus local postcode helpers. Contract: SPEC.md §3.6.

The API is the only source of postcodes. Nothing here guesses a code, state, LGA or place name.
"""

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx

BASE_URL = "https://api.postcode.gov.ng"
TIMEOUT_S = 5.0
REVERSE_RADII_M = (50, 250)  # tight radius first; wider retry only if nothing was found
AUTH_ERROR_CODES = {"auth_required", "invalid_api_key"}  # both seen live (3 and 9 Oct 2026)
RETRY_AFTER_429_S = 2.0
STATES_PATH = Path(__file__).resolve().parents[2] / "data" / "states.json"

# state · LGA · district · area · building, e.g. LA-11-A12-GN-01. Separators may be "-", a space or nothing.
_PARTS = r"([A-Z]{2})[\s-]?(\d{2})[\s-]?([A-Z0-9]{3})[\s-]?([A-Z]{2})[\s-]?(\d{2})"
POSTCODE_RE = re.compile(rf"\b{_PARTS}\b", re.IGNORECASE)
_FULL_RE = re.compile(rf"\s*{_PARTS}\s*", re.IGNORECASE)

# "auth" (bad, missing or revoked key) is our failure, never "no postcode here": the user gets the generic
# error message and the log/alert carry the API's error code.
ErrorKind = Literal["auth", "credits", "rate_limited", "timeout", "unavailable", "level_not_granted"]


class PostcodeError(Exception):
    """An API failure the orchestrator turns into a localised message. `kind` picks the message."""

    def __init__(self, kind: ErrorKind, detail: str = "", code: str | None = None) -> None:
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind
        self.code = code  # the API's error code, e.g. "invalid_api_key"; None when there was no body


@dataclass(frozen=True)
class ReverseResult:
    found: bool
    postcode: str | None = None
    display: str | None = None
    confidence: str | None = None
    distance_m: float | None = None


@dataclass(frozen=True)
class LookupResult:
    postcode: str
    valid: bool
    status: str  # "valid" | "not_found" | "bad_format" | other API status


# ---------------------------------------------------------------- local helpers


def _join(match: re.Match[str]) -> str:
    return "-".join(match.groups()).upper()


def find_postcode(text: str) -> str | None:
    """First postcode anywhere in free text (typed or ASR), normalised to LA-11-A12-GN-01 form."""
    match = POSTCODE_RE.search(text or "")
    return _join(match) if match else None


def normalise(code: str) -> str | None:
    """Normalise a string that is exactly one postcode; None if it is anything else."""
    match = _FULL_RE.fullmatch(code or "")
    return _join(match) if match else None


def display(code: str) -> str:
    """Spoken/printed form with spaces: LA 11 A12 GN 01."""
    return code.replace("-", " ")


def load_states(path: Path = STATES_PATH) -> dict[str, str]:
    """Verified state codes -> state names from data/states.json."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {code: entry["name"] for code, entry in data["codes"].items()}


def segments(code: str, states: dict[str, str]) -> list[tuple[str, str | None]]:
    """Split a postcode into its five parts. Only the state gets a name, and only if it is verified."""
    normalised = normalise(code)
    if normalised is None:
        raise ValueError(f"not a postcode: {code!r}")
    state, *rest = normalised.split("-")
    return [(state, states.get(state))] + [(part, None) for part in rest]


# ---------------------------------------------------------------- API client


def _error_code(body: Any) -> str | None:
    if not isinstance(body, dict):
        return None
    error = body.get("error")
    if isinstance(error, dict):
        return error.get("code")
    if isinstance(error, str):
        return error
    return body.get("code")


def _data(body: Any) -> dict[str, Any]:
    if isinstance(body, dict):
        data = body.get("data", body)
        if isinstance(data, dict):
            return data
    return {}


class PostcodeClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = BASE_URL,
        timeout_s: float = TIMEOUT_S,
        retry_delay: float = RETRY_AFTER_429_S,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.timeout_s = timeout_s
        self._retry_delay = retry_delay
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-API-Key": api_key},
            timeout=timeout_s,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def reverse(self, lat: float, lng: float) -> ReverseResult:
        """Nearest building postcode: within 50 m first, then once more within 250 m.

        Coordinates are used for these calls only and never stored.
        """
        result = ReverseResult(found=False)
        for radius in REVERSE_RADII_M:
            status, body = await self._get(
                "/v1/search/reverse", {"lat": lat, "lng": lng, "max_distance_m": radius}
            )
            self._raise_for(status, body)
            result = self._parse_reverse(body)
            if result.found:
                break
        return result

    @staticmethod
    def _parse_reverse(body: Any) -> ReverseResult:
        data = _data(body)
        unit = data.get("unit") or {}
        postcode = normalise(str(unit.get("postcode", "")))
        if not data.get("found") or postcode is None:
            return ReverseResult(found=False)
        distance = unit.get("distance_m")
        return ReverseResult(
            found=True,
            postcode=postcode,
            display=display(postcode),
            confidence=unit.get("confidence"),
            distance_m=float(distance) if distance is not None else None,
        )

    async def lookup(self, code: str) -> LookupResult:
        """Level 1 validity check. A malformed code never reaches the API."""
        postcode = normalise(code)
        if postcode is None:
            return LookupResult(code, False, "bad_format")
        status, body = await self._get("/v1/lookup", {"code": postcode, "level": 1})
        if status == 404 and _error_code(body) not in AUTH_ERROR_CODES:
            return LookupResult(postcode, False, "not_found")
        self._raise_for(status, body)
        data = _data(body)
        valid = data.get("valid") is True or data.get("status") == "valid"
        return LookupResult(postcode, valid, str(data.get("status") or ("valid" if valid else "not_found")))

    async def _get(self, path: str, params: dict[str, Any]) -> tuple[int, Any]:
        """GET with one retry after a 429. Returns (status, parsed JSON body)."""
        for attempt in range(2):
            try:
                response = await self._http.get(path, params=params)
            except httpx.TimeoutException as exc:
                raise PostcodeError("timeout", path) from exc
            except httpx.HTTPError as exc:
                raise PostcodeError("unavailable", f"{path}: {type(exc).__name__}") from exc
            if response.status_code == 429:
                if attempt == 0:
                    await asyncio.sleep(self._retry_delay)
                    continue
                raise PostcodeError("rate_limited", path)
            try:
                return response.status_code, response.json()
            except ValueError as exc:
                raise PostcodeError("unavailable", f"{path}: non-JSON {response.status_code}") from exc
        raise AssertionError("unreachable")

    @staticmethod
    def _raise_for(status: int, body: Any) -> None:
        code = _error_code(body)
        if status < 400 and code is None:
            return
        # Error codes seen live: auth_required (no key), level_not_granted (level above our L1 key).
        if code == "level_not_granted":
            raise PostcodeError("level_not_granted", f"{status} {code}", code)
        if code in AUTH_ERROR_CODES or status in (401, 403):
            raise PostcodeError("auth", f"{status} {code}", code)
        if status == 402:
            raise PostcodeError("credits", f"{status} {code}", code)
        raise PostcodeError("unavailable", f"{status} {code}", code)
