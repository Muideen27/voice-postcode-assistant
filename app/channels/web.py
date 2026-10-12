"""Web channel: turns HTTP requests into Events and returns the orchestrator's Reply as JSON. Contract:
SPEC.md §3.7. No logic lives here; the browser session UUID is hashed before anything else sees it.
"""

import asyncio
import hashlib
import re
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from app.events import LANGS, Event, Lang, Reply
from app.services.asr import MAX_BYTES
from app.store import hash_user

_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_FONT_RE = re.compile(r"[a-z0-9-]+\.woff2")
FONT_CACHE = "public, max-age=31536000, immutable"
WARM_COOLDOWN_S = 120.0  # a warm-up request already waits out a full cold start
MAX_TEXT = 500

Handler = Callable[[Event], Awaitable[Reply]]
Warmer = Callable[[], Awaitable[None]]


class SessionIn(BaseModel):
    session: str


class LanguageIn(BaseModel):
    session: str
    lang: Lang


class ConsentIn(BaseModel):
    session: str
    agree: bool


class LocationIn(BaseModel):
    session: str
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float | None = None  # accepted for the contract; not stored or logged


class TextIn(BaseModel):
    session: str
    text: str = Field(min_length=1, max_length=MAX_TEXT)


class FeedbackIn(BaseModel):
    session: str
    helpful: bool | None = None
    knew_before: bool | None = None
    skipped: bool = False  # knew_before question skipped (sent with knew_before null)


class RateLimiter:
    """Sliding-window request limit per client, kept in memory only (never stored or logged).

    Protects the GPU-backed routes from a bot during judging. Per web container; one is always on, so
    in practice it is global. Limits are generous because on-site testers often share one WiFi IP.
    """

    def __init__(self, limit: int, window_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window_s = window_s
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        now = self._clock()
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= self.window_s:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        if len(self._hits) > 10_000:  # forget idle clients so memory stays small
            self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < self.window_s}
        return True


def default_limits() -> dict[str, RateLimiter]:
    return {
        "voice": RateLimiter(60, 600),  # ASR GPU
        "text": RateLimiter(120, 600),  # LLM GPU
        "warm": RateLimiter(150, 60),  # the page polls this every 8-15 s while a model is cold
    }


def client_key(request: Request) -> str:
    """Hashed client IP (first X-Forwarded-For hop behind Modal's proxy). Held in memory only."""
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")
    return hashlib.sha256(ip.encode()).hexdigest()[:16]


def create_api(
    handle: Handler,
    salt: str,
    web_dir: Path,
    templates: dict[Lang, dict[str, str]],
    warmers: list[Warmer] | None = None,
    on_start: list[Warmer] | None = None,
    stats: Callable[[], Awaitable[dict[str, Any]]] | None = None,
    readiness: Callable[[], Awaitable[dict[str, bool]]] | None = None,
    limits: dict[str, RateLimiter] | None = None,
) -> FastAPI:
    limiters = limits if limits is not None else default_limits()

    def check_rate(name: str, request: Request) -> None:
        limiter = limiters.get(name)
        if limiter is not None and not limiter.allow(client_key(request)):
            raise HTTPException(status_code=429, detail="too many requests", headers={"Retry-After": "60"})

    background: set[asyncio.Task[Any]] = set()  # keep references so background tasks are not collected

    def spawn(job: Warmer) -> None:
        task = asyncio.create_task(job())
        background.add(task)
        task.add_done_callback(background.discard)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        for job in on_start or []:  # e.g. the Postcode API data canary; never blocks start-up
            spawn(job)
        yield

    api = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    def user(session: str) -> str:
        if not _UUID_RE.fullmatch(session or ""):
            raise HTTPException(status_code=400, detail="bad session")
        return hash_user(salt, "web", session.lower())

    async def reply(event: Event) -> JSONResponse:
        result = await handle(event)
        return JSONResponse(asdict(result), headers={"Cache-Control": "no-store"})

    def event(session: str, type_: str, lang: Lang | None = None, **fields: Any) -> Event:
        return Event(user_hash=user(session), channel="web", type=type_, lang=lang, **fields)  # type: ignore[arg-type]

    # ---------------------------------------------------------------- static

    @api.get("/")
    async def index() -> FileResponse:
        return FileResponse(
            web_dir / "index.html", media_type="text/html", headers={"Cache-Control": "no-cache"}
        )

    @api.get("/fonts/{name}")
    async def font(name: str) -> FileResponse:
        path = web_dir / "fonts" / name
        if not _FONT_RE.fullmatch(name) or not path.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(path, media_type="font/woff2", headers={"Cache-Control": FONT_CACHE})

    @api.get("/api/stats")
    async def pilot_stats() -> JSONResponse:
        """Pilot dashboard numbers (real log rows from PILOT_START only; never transcripts or user hashes)."""
        if stats is None:
            raise HTTPException(status_code=404)
        return JSONResponse(await stats(), headers={"Cache-Control": "no-store"})

    @api.get("/api/strings/{lang}")
    async def strings(lang: str) -> JSONResponse:
        """All template strings for one language (the page renders nothing that is not in a template)."""
        if lang not in LANGS:
            raise HTTPException(status_code=404)
        return JSONResponse(templates[lang], headers={"Cache-Control": "public, max-age=300"})

    last_warm = {"at": -WARM_COOLDOWN_S}

    @api.get("/api/warm")
    async def warm(request: Request) -> JSONResponse:
        """Which GPUs are ready ({"llm", "asr"}), bounded to ~3 s. If either is cold, start the warm-ups in
        the background (not again within WARM_COOLDOWN_S). The page polls this while something is cold."""
        check_rate("warm", request)
        status = {"llm": True, "asr": True}
        if readiness is not None:
            try:
                status = await asyncio.wait_for(readiness(), 3.0)
            except Exception:
                status = {"llm": False, "asr": False}
        loop_now = asyncio.get_running_loop().time()
        if not all(status.values()) and loop_now - last_warm["at"] >= WARM_COOLDOWN_S:
            last_warm["at"] = loop_now
            for warmer in warmers or []:
                spawn(warmer)
        return JSONResponse(status, headers={"Cache-Control": "no-store"})

    # ---------------------------------------------------------------- conversation

    @api.post("/api/language")
    async def language(body: LanguageIn) -> JSONResponse:
        return await reply(event(body.session, "choice", body.lang, text=body.lang))

    @api.post("/api/consent")
    async def consent(body: ConsentIn) -> JSONResponse:
        return await reply(event(body.session, "choice", text="agree" if body.agree else "decline"))

    @api.post("/api/location")
    async def location(body: LocationIn) -> JSONResponse:
        return await reply(event(body.session, "location", lat=body.lat, lng=body.lng))

    @api.post("/api/location-denied")
    async def location_denied(body: SessionIn) -> JSONResponse:
        """The browser refused or failed geolocation: no coordinates -> location_denied template."""
        return await reply(event(body.session, "location"))

    @api.post("/api/voice")
    async def voice(
        request: Request,
        session: Annotated[str, Form()],
        audio: Annotated[UploadFile, File()],
    ) -> JSONResponse:
        check_rate("voice", request)
        data = await audio.read(MAX_BYTES + 1)  # the ASR service rejects anything over the limit
        return await reply(event(session, "voice", audio=data, audio_mime=audio.content_type))

    @api.post("/api/text")
    async def text(body: TextIn, request: Request) -> JSONResponse:
        check_rate("text", request)
        return await reply(event(body.session, "text", text=body.text))

    @api.post("/api/feedback")
    async def feedback(body: FeedbackIn) -> JSONResponse:
        if body.helpful is not None:
            return await reply(event(body.session, "feedback", text="yes" if body.helpful else "no"))
        if body.knew_before is not None or body.skipped:
            answer = "skip" if body.knew_before is None else "yes" if body.knew_before else "no"
            return await reply(event(body.session, "choice", text=answer))
        raise HTTPException(status_code=422, detail="helpful or knew_before required")

    return api
