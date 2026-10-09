"""Web channel: turns HTTP requests into Events and returns the orchestrator's Reply as JSON. Contract:
SPEC.md §3.7. No logic lives here; the browser session UUID is hashed before anything else sees it.
"""

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from app.events import LANGS, Event, Lang, Reply
from app.services.asr import MAX_BYTES
from app.store import hash_user

_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_FONT_RE = re.compile(r"[a-z0-9-]+\.woff2")
FONT_CACHE = "public, max-age=31536000, immutable"
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


def create_api(
    handle: Handler,
    salt: str,
    web_dir: Path,
    templates: dict[Lang, dict[str, str]],
    warmers: list[Warmer] | None = None,
) -> FastAPI:
    api = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    background: set[asyncio.Task[None]] = set()  # keep references so warm-up tasks are not collected

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

    @api.get("/api/strings/{lang}")
    async def strings(lang: str) -> JSONResponse:
        """All template strings for one language (the page renders nothing that is not in a template)."""
        if lang not in LANGS:
            raise HTTPException(status_code=404)
        return JSONResponse(templates[lang], headers={"Cache-Control": "public, max-age=300"})

    @api.get("/api/warm", status_code=204)
    async def warm() -> Response:
        """Start the GPUs in the background and return at once; the page calls this on load."""
        for warmer in warmers or []:
            task = asyncio.create_task(warmer())
            background.add(task)
            task.add_done_callback(background.discard)
        return Response(status_code=204)

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
        session: Annotated[str, Form()],
        audio: Annotated[UploadFile, File()],
    ) -> JSONResponse:
        data = await audio.read(MAX_BYTES + 1)  # the ASR service rejects anything over the limit
        return await reply(event(session, "voice", audio=data, audio_mime=audio.content_type))

    @api.post("/api/text")
    async def text(body: TextIn) -> JSONResponse:
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
