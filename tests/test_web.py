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


def test_warm_returns_at_once_and_runs_warmers(web: Any) -> None:
    client, _, warmed = web
    assert client.get("/api/warm").status_code == 204
    client.get("/")  # give the event loop a turn
    assert warmed == ["gpu"]


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


def test_stats_route_and_optional_asset(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("x")

    async def stats() -> dict[str, Any]:
        return {"kpis": {"interactions": 0}}

    client = TestClient(create_api(Recorder(), "salt", tmp_path, T, stats=stats))
    assert client.get("/api/stats").json() == {"kpis": {"interactions": 0}}
    assert client.get("/assets/footer.webp").status_code == 404  # missing file: the page hides the slot
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "footer.webp").write_bytes(b"RIFF....WEBP")
    assert client.get("/assets/footer.webp").headers["content-type"] == "image/webp"
    assert client.get("/assets/../index.html").status_code == 404
    assert TestClient(create_api(Recorder(), "salt", tmp_path, T)).get("/api/stats").status_code == 404
