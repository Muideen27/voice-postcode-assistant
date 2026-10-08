"""Sessions (Modal Dict) and the interaction log (Modal Volume, JSONL). Contract: SPEC.md §3.8-3.9.

Privacy: the only user identifier stored anywhere is `hash_user(...)`. Log rows have no field for
coordinates, raw session IDs or audio, and `LogRow` rejects anything that is not a 64-hex hash.
"""

import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

from app.events import Lang

WAT = timezone(timedelta(hours=1), "WAT")
_HASH_RE = re.compile(r"[0-9a-f]{64}")

Channel = Literal["web"]
InputKind = Literal["voice", "text", "location", "choice"]
Feedback = Literal["yes", "no"]


def hash_user(salt: str, channel: Channel, session_id: str) -> str:
    """sha256(HASH_SALT + channel + ":" + session id). One-way; the raw id is never stored."""
    if not salt:
        raise ValueError("HASH_SALT is empty")
    if not session_id:
        raise ValueError("session id is empty")
    return hashlib.sha256(f"{salt}{channel}:{session_id}".encode()).hexdigest()


def now_wat() -> str:
    return datetime.now(WAT).isoformat(timespec="seconds")


# ---------------------------------------------------------------- sessions


@dataclass
class Session:
    lang: Lang | None = None
    consented: bool = False
    knew_before_asked: bool = False  # asked once, right after the language choice
    awaiting: Literal["knew_before", "feedback"] | None = None  # what the next tap/digit answers
    turns: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Session":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


class SessionStore(Protocol):
    async def get(self, user_hash: str) -> Session: ...
    async def put(self, user_hash: str, session: Session) -> None: ...


class MemorySessionStore:
    """In-process store for tests and local runs."""

    def __init__(self) -> None:
        self.data: dict[str, dict[str, Any]] = {}

    async def get(self, user_hash: str) -> Session:
        return Session.from_dict(self.data.get(user_hash))

    async def put(self, user_hash: str, session: Session) -> None:
        self.data[user_hash] = asdict(session)


class ModalDictSessionStore:
    """Sessions in a `modal.Dict`, shared by all containers. Values are plain dicts, not pickled classes."""

    def __init__(self, modal_dict: Any) -> None:
        self._dict = modal_dict

    async def get(self, user_hash: str) -> Session:
        return Session.from_dict(await self._dict.get.aio(user_hash))

    async def put(self, user_hash: str, session: Session) -> None:
        await self._dict.put.aio(user_hash, asdict(session))


# ---------------------------------------------------------------- interaction log


@dataclass
class Latency:
    asr: int | None = None
    llm: int | None = None
    api: int | None = None
    total: int | None = None


@dataclass
class LogRow:
    """One user turn. Field names and order match the schema in CLAUDE.md."""

    user_hash: str
    lang: Lang | None
    input: InputKind
    reply_kind: str
    channel: Channel = "web"
    transcript: str | None = None
    intent: str | None = None
    postcode_found: bool | None = None
    api_status: str | None = None
    latency_ms: Latency = field(default_factory=Latency)
    feedback: Feedback | None = None
    knew_postcode_before: bool | None = None
    ts: str = field(default_factory=now_wat)

    def __post_init__(self) -> None:
        if not _HASH_RE.fullmatch(self.user_hash):
            raise ValueError("user_hash must be a sha256 hex digest, never a raw id")

    def to_json(self) -> str:
        row = asdict(self)
        ordered = {k: row[k] for k in SCHEMA_FIELDS}
        return json.dumps(ordered, ensure_ascii=False)


SCHEMA_FIELDS = (
    "ts",
    "user_hash",
    "channel",
    "lang",
    "input",
    "transcript",
    "intent",
    "postcode_found",
    "api_status",
    "latency_ms",
    "reply_kind",
    "feedback",
    "knew_postcode_before",
)


class InteractionLog(Protocol):
    async def append(self, row: LogRow) -> None: ...


class MemoryLog:
    def __init__(self) -> None:
        self.rows: list[LogRow] = []

    async def append(self, row: LogRow) -> None:
        self.rows.append(row)


class JsonlLog:
    """Appends rows to `<dir>/interactions-YYYY-MM-DD<suffix>.jsonl` (date in WAT).

    On Modal, `directory` is the mounted Volume, `suffix` is unique per container (so two containers never
    append to the same file) and `commit` is `volume.commit.aio`, so rows survive container shutdown.
    """

    def __init__(
        self,
        directory: Path,
        suffix: str = "",
        commit: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._dir = directory
        self._suffix = f"-{suffix}" if suffix else ""
        self._commit = commit

    def path_for(self, row: LogRow) -> Path:
        return self._dir / f"interactions-{row.ts[:10]}{self._suffix}.jsonl"

    async def append(self, row: LogRow) -> None:
        path = self.path_for(row)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(row.to_json() + "\n")
        if self._commit is not None:
            await self._commit()
