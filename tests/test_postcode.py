"""Postcode client tests. No network: every HTTP call goes through httpx.MockTransport."""

import asyncio
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from app.services.postcode import (
    LookupResult,
    PostcodeClient,
    PostcodeError,
    ReverseResult,
    display,
    find_postcode,
    load_states,
    normalise,
    segments,
)

FIXTURES = Path(__file__).parent / "fixtures" / "postcode"
VALID = "LA-11-A12-GN-01"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def make_client(handler: Callable[[httpx.Request], httpx.Response]) -> PostcodeClient:
    return PostcodeClient(api_key="test-key", transport=httpx.MockTransport(handler), retry_delay=0)


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- regex and normalise


@pytest.mark.parametrize(
    "text",
    [
        "LA-11-A12-GN-01",
        "la-11-a12-gn-01",
        "LA 11 A12 GN 01",
        "la11a12gn01",
        "Is LA 11 A12 GN 01 my correct postcode?",
        "ṣé la-11-a12-gn-01 tọ̀nà?",
    ],
)
def test_find_postcode_variants(text: str) -> None:
    assert find_postcode(text) == VALID


@pytest.mark.parametrize(
    "text",
    ["", "what is my postcode", "LA-11-A12-GN", "call 08012345678", "LA-1-A12-GN-01", "XLA-11-A12-GN-01"],
)
def test_find_postcode_none(text: str) -> None:
    assert find_postcode(text) is None


def test_normalise_rejects_extra_text() -> None:
    assert normalise(" la 11 a12 gn 01 ") == VALID
    assert normalise("my code LA-11-A12-GN-01") is None


def test_display() -> None:
    assert display(VALID) == "LA 11 A12 GN 01"


# ---------------------------------------------------------------- segments and states


def test_states_holds_only_documented_codes() -> None:
    assert load_states() == {
        "AK": "Akwa Ibom",
        "BA": "Bauchi",
        "EB": "Ebonyi",
        "EK": "Ekiti",
        "EN": "Enugu",
        "FC": "Federal Capital Territory",
        "JI": "Jigawa",
        "KN": "Kano",
        "LA": "Lagos",
        "NI": "Niger",
        "OG": "Ogun",
    }


def test_segments_known_state() -> None:
    assert segments(VALID, {"LA": "Lagos"}) == [
        ("LA", "Lagos"),
        ("11", None),
        ("A12", None),
        ("GN", None),
        ("01", None),
    ]


def test_segments_unknown_state_is_not_guessed() -> None:
    assert segments("OY-31-F82-WJ-80", load_states())[0] == ("OY", None)


def test_segments_bad_code() -> None:
    with pytest.raises(ValueError):
        segments("not a code", {})


# ---------------------------------------------------------------- reverse


def not_found_at(radius: int) -> dict:
    return {"data": {"found": False, "radius_m": radius}}


def test_reverse_found_within_50m_makes_one_call() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=fixture("reverse_found.json"))

    result = run(make_client(handler).reverse(6.6018, 3.3515))

    assert result == ReverseResult(
        found=True, postcode=VALID, display="LA 11 A12 GN 01", confidence="high", distance_m=9.2
    )
    assert len(seen) == 1
    req = seen[0]
    assert req.url.path == "/v1/search/reverse"
    assert req.headers["X-API-Key"] == "test-key"
    assert req.url.params["max_distance_m"] == "50"
    assert float(req.url.params["lat"]) == 6.6018
    assert float(req.url.params["lng"]) == 3.3515


def test_reverse_retries_once_at_250m() -> None:
    radii: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        radius = request.url.params["max_distance_m"]
        radii.append(radius)
        if radius == "50":
            return httpx.Response(200, json=not_found_at(50))
        return httpx.Response(200, json=fixture("reverse_found.json"))

    result = run(make_client(handler).reverse(6.6018, 3.3515))

    assert radii == ["50", "250"]
    assert result.found and result.postcode == VALID
    assert result.distance_m == 9.2 and result.confidence == "high"


def test_reverse_not_found_at_either_radius() -> None:
    radii: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        radii.append(request.url.params["max_distance_m"])
        if radii[-1] == "250":
            return httpx.Response(200, json=fixture("reverse_not_found.json"))
        return httpx.Response(200, json=not_found_at(50))

    assert run(make_client(handler).reverse(9.0, 7.0)) == ReverseResult(found=False)
    assert radii == ["50", "250"]


# ---------------------------------------------------------------- lookup


def test_lookup_valid() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=fixture("lookup_valid.json"))

    assert run(make_client(handler).lookup("la 11 a12 gn 01")) == LookupResult(VALID, True, "valid")
    assert seen[0].url.path == "/v1/lookup"
    assert seen[0].url.params["code"] == VALID
    assert seen[0].url.params["level"] == "1"


def test_lookup_not_found_is_never_valid() -> None:
    client = make_client(lambda r: httpx.Response(200, json=fixture("lookup_not_found.json")))
    assert run(client.lookup("LA-11-W06-TC-10")) == LookupResult("LA-11-W06-TC-10", False, "not_found")


def test_lookup_404_is_not_found() -> None:
    client = make_client(lambda r: httpx.Response(404, json={"error": {"code": "not_found"}}))
    assert run(client.lookup("LA-11-W06-TC-10")).status == "not_found"


def test_lookup_bad_format_skips_api() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("API must not be called for a malformed code")

    assert run(make_client(handler).lookup("LA-11")) == LookupResult("LA-11", False, "bad_format")


@pytest.mark.parametrize("status", [400, 403])
def test_level_not_granted_is_its_own_kind(status: int) -> None:
    client = make_client(lambda r: httpx.Response(status, json=fixture("error_level_not_granted.json")))
    with pytest.raises(PostcodeError) as err:
        run(client.lookup(VALID))
    assert err.value.kind == "level_not_granted"


@pytest.mark.parametrize("status", [400, 401])
def test_auth_required_is_config_error(status: int) -> None:
    client = make_client(lambda r: httpx.Response(status, json=fixture("error_auth_required.json")))
    with pytest.raises(PostcodeError) as err:
        run(client.reverse(6.6, 3.3))
    assert err.value.kind == "config"


# ---------------------------------------------------------------- error mapping


@pytest.mark.parametrize(
    ("status", "kind"),
    [(401, "config"), (403, "config"), (402, "credits"), (500, "unavailable"), (503, "unavailable")],
)
def test_http_errors_map_to_kinds(status: int, kind: str) -> None:
    client = make_client(lambda r: httpx.Response(status, json={"error": {"code": "x"}}))
    with pytest.raises(PostcodeError) as err:
        run(client.reverse(6.6, 3.3))
    assert err.value.kind == kind


def test_429_retries_once_then_succeeds() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429)
        return httpx.Response(200, json=fixture("reverse_found.json"))

    assert run(make_client(handler).reverse(6.6018, 3.3515)).found is True
    assert calls == 2


def test_429_twice_is_rate_limited() -> None:
    client = make_client(lambda r: httpx.Response(429))
    with pytest.raises(PostcodeError) as err:
        run(client.reverse(6.6, 3.3))
    assert err.value.kind == "rate_limited"


def test_timeout_maps_to_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(PostcodeError) as err:
        run(make_client(handler).reverse(6.6, 3.3))
    assert err.value.kind == "timeout"


def test_network_error_maps_to_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(PostcodeError) as err:
        run(make_client(handler).lookup(VALID))
    assert err.value.kind == "unavailable"


def test_non_json_body_maps_to_unavailable() -> None:
    client = make_client(lambda r: httpx.Response(200, text="<html>gateway</html>"))
    with pytest.raises(PostcodeError) as err:
        run(client.reverse(6.6, 3.3))
    assert err.value.kind == "unavailable"


def test_default_timeout_is_5s() -> None:
    assert PostcodeClient(api_key="k").timeout_s == 5.0
