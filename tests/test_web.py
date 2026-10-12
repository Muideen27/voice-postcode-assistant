"""Web channel tests: HTTP -> Event mapping, validation, static files. No network, no Modal."""

import asyncio
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.channels.web import FONT_CACHE, create_api
from app.events import Event, Reply
from app.orchestrator import load_templates
from app.store import hash_user

SESSION = str(uuid.uuid4())
T = load_templates()


class Recorder:
    def __init__(self) -> None:
        self.events: list[Event] = []

    async def __call__(self, event: Event) -> Reply:
        self.events.append(event)
        return Reply(kind="menu", lang=event.lang or "en", text="ok")


@pytest.fixture
def web(tmp_path: Path) -> tuple[TestClient, Recorder, list[str]]:
    (tmp_path / "fonts").mkdir()
    (tmp_path / "fonts" / "atkinson-400.woff2").write_bytes(b"wOF2")
    (tmp_path / "index.html").write_text("<title>Postcode</title>")
    recorder, warmed = Recorder(), []

    async def warmer() -> None:
        await asyncio.sleep(0)
        warmed.append("gpu")

    api = create_api(recorder, "salt", tmp_path, T, warmers=[warmer])
    return TestClient(api), recorder, warmed


def last(recorder: Recorder) -> Event:
    return recorder.events[-1]


def test_session_is_hashed_never_passed_raw(web: Any) -> None:
    client, recorder, _ = web
    assert client.post("/api/language", json={"session": SESSION, "lang": "yo"}).status_code == 200
    event = last(recorder)
    assert event.user_hash == hash_user("salt", "web", SESSION) and SESSION not in repr(event)
    assert (event.type, event.lang, event.text, event.channel) == ("choice", "yo", "yo", "web")


@pytest.mark.parametrize("session", ["", "not-a-uuid", "../../etc/passwd"])
def test_bad_session_is_rejected(web: Any, session: str) -> None:
    client, recorder, _ = web
    assert client.post("/api/text", json={"session": session, "text": "hi"}).status_code == 400
    assert recorder.events == []


def test_reply_is_returned_as_json(web: Any) -> None:
    client, _, _ = web
    body = client.post("/api/text", json={"session": SESSION, "text": "hello"}).json()
    assert body == {
        "kind": "menu",
        "lang": "en",
        "text": "ok",
        "postcode": None,
        "segments": None,
        "confidence": None,
        "transcript": None,
        "distance_m": None,
    }


@pytest.mark.parametrize(("agree", "text"), [(True, "agree"), (False, "decline")])
def test_consent(web: Any, agree: bool, text: str) -> None:
    client, recorder, _ = web
    client.post("/api/consent", json={"session": SESSION, "agree": agree})
    assert (last(recorder).type, last(recorder).text) == ("choice", text)


def test_location_passes_coordinates_and_validates_range(web: Any) -> None:
    client, recorder, _ = web
    client.post("/api/location", json={"session": SESSION, "lat": 6.6018, "lng": 3.3515, "accuracy_m": 12})
    assert (last(recorder).type, last(recorder).lat, last(recorder).lng) == ("location", 6.6018, 3.3515)
    assert client.post("/api/location", json={"session": SESSION, "lat": 99, "lng": 3}).status_code == 422


def test_location_denied_sends_a_location_event_without_coordinates(web: Any) -> None:
    client, recorder, _ = web
    client.post("/api/location-denied", json={"session": SESSION})
    assert (last(recorder).type, last(recorder).lat) == ("location", None)


def test_text_length_limit(web: Any) -> None:
    client, recorder, _ = web
    assert client.post("/api/text", json={"session": SESSION, "text": "a" * 501}).status_code == 422
    assert client.post("/api/text", json={"session": SESSION, "text": ""}).status_code == 422
    assert recorder.events == []


def test_voice_upload(web: Any) -> None:
    client, recorder, _ = web
    files = {"audio": ("note.webm", b"\x1a\x45\xdf\xa3", "audio/webm;codecs=opus")}
    assert client.post("/api/voice", data={"session": SESSION}, files=files).status_code == 200
    event = last(recorder)
    assert (event.type, event.audio, event.audio_mime) == (
        "voice",
        b"\x1a\x45\xdf\xa3",
        "audio/webm;codecs=opus",
    )


@pytest.mark.parametrize(
    ("body", "type_", "text"),
    [
        ({"helpful": True}, "feedback", "yes"),
        ({"helpful": False}, "feedback", "no"),
        ({"knew_before": True}, "choice", "yes"),
        ({"knew_before": False}, "choice", "no"),
        ({"knew_before": None, "skipped": True}, "choice", "skip"),
    ],
)
def test_feedback_and_knew_before(web: Any, body: dict[str, Any], type_: str, text: str) -> None:
    client, recorder, _ = web
    assert client.post("/api/feedback", json={"session": SESSION, **body}).status_code == 200
    assert (last(recorder).type, last(recorder).text) == (type_, text)


def test_feedback_needs_an_answer(web: Any) -> None:
    client, _, _ = web
    assert client.post("/api/feedback", json={"session": SESSION}).status_code == 422


def test_index_fonts_and_strings(web: Any) -> None:
    client, _, _ = web
    assert "Postcode" in client.get("/").text
    font = client.get("/fonts/atkinson-400.woff2")
    assert font.status_code == 200 and font.headers["cache-control"] == FONT_CACHE
    assert client.get("/fonts/../index.html").status_code == 404
    assert client.get("/fonts/missing.woff2").status_code == 404
    strings = client.get("/api/strings/ha").json()
    assert strings["btn_location"] == T["ha"]["btn_location"] and "_todo_review" not in strings
    assert client.get("/api/strings/fr").status_code == 404


def test_warm_reports_readiness_and_starts_warmers_only_when_cold(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("x")
    state = {"llm": False, "asr": True}
    started: list[str] = []

    async def warmer() -> None:
        started.append("gpu")

    async def ready() -> dict[str, bool]:
        return dict(state)

    with TestClient(create_api(Recorder(), "salt", tmp_path, T, warmers=[warmer], readiness=ready)) as client:
        assert client.get("/api/warm").json() == {"llm": False, "asr": True}
        assert client.get("/api/warm").json() == {"llm": False, "asr": True}  # cooldown: no second warm-up
        state["llm"] = True
        assert client.get("/api/warm").json() == {"llm": True, "asr": True}
    assert started == ["gpu"]


def test_warm_never_hangs_on_a_slow_readiness_check(tmp_path: Path) -> None:
    import time

    (tmp_path / "index.html").write_text("x")

    async def slow() -> dict[str, bool]:
        await asyncio.sleep(30)
        return {"llm": True, "asr": True}

    with TestClient(create_api(Recorder(), "salt", tmp_path, T, readiness=slow)) as client:
        started = time.perf_counter()
        assert client.get("/api/warm").json() == {"llm": False, "asr": False}
        assert time.perf_counter() - started < 4


def test_on_start_jobs_run_when_the_app_starts(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("x")
    ran: list[str] = []

    async def canary() -> None:
        ran.append("canary")

    with TestClient(create_api(Recorder(), "salt", tmp_path, T, on_start=[canary])) as client:
        client.get("/")
    assert ran == ["canary"]


def test_slow_startup_jobs_never_block_the_page(tmp_path: Path) -> None:
    import time

    (tmp_path / "index.html").write_text("page")

    async def slow_canary() -> None:
        await asyncio.sleep(30)  # e.g. an unreachable Postcode API

    started = time.perf_counter()
    with TestClient(create_api(Recorder(), "salt", tmp_path, T, on_start=[slow_canary])) as client:
        assert client.get("/").text == "page"
        assert client.get("/api/strings/en").status_code == 200
        assert time.perf_counter() - started < 2.0


def test_stats_route(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("x")

    async def stats() -> dict[str, Any]:
        return {"kpis": {"interactions": 0}}

    client = TestClient(create_api(Recorder(), "salt", tmp_path, T, stats=stats))
    assert client.get("/api/stats").json() == {"kpis": {"interactions": 0}}
    assert client.get("/assets/footer.webp").status_code == 404  # no image slot: text attribution only
    assert TestClient(create_api(Recorder(), "salt", tmp_path, T)).get("/api/stats").status_code == 404


# ---------------------------------------------------------------- rate limits


def test_rate_limiter_sliding_window() -> None:
    from app.channels.web import RateLimiter

    now = [0.0]
    limiter = RateLimiter(2, 10, clock=lambda: now[0])
    assert limiter.allow("a") and limiter.allow("a")
    assert not limiter.allow("a")
    assert limiter.allow("b")  # another client is independent
    now[0] = 10.0
    assert limiter.allow("a")  # the window has moved on


def test_gpu_routes_return_429_over_the_limit(tmp_path: Path) -> None:
    from app.channels.web import RateLimiter

    (tmp_path / "index.html").write_text("x")
    limits = {"voice": RateLimiter(1, 600), "text": RateLimiter(1, 600), "warm": RateLimiter(1, 60)}
    client = TestClient(create_api(Recorder(), "salt", tmp_path, T, limits=limits))
    ip_a, ip_b = {"x-forwarded-for": "198.51.100.7"}, {"x-forwarded-for": "203.0.113.9, 10.0.0.1"}
    body = {"session": SESSION, "text": "hi"}
    assert client.post("/api/text", json=body, headers=ip_a).status_code == 200
    blocked = client.post("/api/text", json=body, headers=ip_a)
    assert blocked.status_code == 429 and blocked.headers["retry-after"] == "60"
    assert client.post("/api/text", json=body, headers=ip_b).status_code == 200  # other client unaffected
    files = {"audio": ("n.webm", b"x", "audio/webm")}
    assert client.post("/api/voice", data={"session": SESSION}, files=files, headers=ip_a).status_code == 200
    assert client.post("/api/voice", data={"session": SESSION}, files=files, headers=ip_a).status_code == 429
    assert client.get("/api/warm", headers=ip_a).status_code == 200
    assert client.get("/api/warm", headers=ip_a).status_code == 429
    # location, consent and the page itself are never limited (no GPU)
    for _ in range(3):
        assert (
            client.post(
                "/api/location", json={"session": SESSION, "lat": 6.6, "lng": 3.3}, headers=ip_a
            ).status_code
            == 200
        )


def test_default_limits_are_generous_for_shared_wifi() -> None:
    from app.channels.web import default_limits

    limits = default_limits()
    assert (limits["voice"].limit, limits["voice"].window_s) == (60, 600)
    assert (limits["text"].limit, limits["warm"].limit) == (120, 150)
