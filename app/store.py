"""Sessions (Modal Dict) and the interaction log (Modal Volume, JSONL). Contract: SPEC.md §3.8-3.9.

Privacy: the only user identifier stored anywhere is `hash_user(...)`. Log rows have no field for
coordinates, raw session IDs or audio, and `LogRow` rejects anything that is not a 64-hex hash.
"""

import hashlib
import json
import re
import time
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


Stage = Literal["new", "consent", "knew_before", "ready"]
LlmStatus = Literal["ok", "timeout", "error", "bad_json"]


@dataclass
class Session:
    # new (language menu) -> consent -> knew_before -> ready. knew_before is passed once per user.
    # A "new" session is never stored: it exists only until a language is chosen.
    stage: Stage = "new"
    lang: Lang | None = None
    awaiting_feedback: bool = False  # a bare "1"/"2" typed now answers "Did this help?"
    turns: int = 0
    updated_ts: float = 0.0  # unix seconds of the last write; used only for the unconsented-session TTL

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Session":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


class SessionStore(Protocol):
    async def get(self, user_hash: str) -> Session: ...
    async def put(self, user_hash: str, session: Session) -> None: ...
    async def delete(self, user_hash: str) -> None: ...


class MemorySessionStore:
    """In-process store for tests and local runs."""

    def __init__(self) -> None:
        self.data: dict[str, dict[str, Any]] = {}

    async def get(self, user_hash: str) -> Session:
        return Session.from_dict(self.data.get(user_hash))

    async def put(self, user_hash: str, session: Session) -> None:
        self.data[user_hash] = asdict(session)

    async def delete(self, user_hash: str) -> None:
        self.data.pop(user_hash, None)


UNCONSENTED_TTL_S = 30 * 60


class TtlSessionStore:
    """Wraps a store: a session still waiting for consent expires 30 minutes after its last write.

    Expired sessions read as new (and are deleted). `sweep()` removes the ones nobody comes back to;
    main.py runs it on a schedule. Consented sessions are never expired here.
    """

    def __init__(
        self, inner: SessionStore, ttl_s: float = UNCONSENTED_TTL_S, clock: Callable[[], float] = time.time
    ) -> None:
        self._inner = inner
        self._ttl_s = ttl_s
        self._clock = clock

    def expired(self, session: Session) -> bool:
        return session.stage == "consent" and self._clock() - session.updated_ts > self._ttl_s

    async def get(self, user_hash: str) -> Session:
        session = await self._inner.get(user_hash)
        if self.expired(session):
            await self._inner.delete(user_hash)
            return Session()
        return session

    async def put(self, user_hash: str, session: Session) -> None:
        session.updated_ts = self._clock()
        await self._inner.put(user_hash, session)

    async def delete(self, user_hash: str) -> None:
        await self._inner.delete(user_hash)

    async def sweep(self, items: list[tuple[str, dict[str, Any]]]) -> int:
        """Delete expired unconsented sessions from (user_hash, stored dict) pairs. Returns the count."""
        removed = 0
        for user_hash, data in items:
            if self.expired(Session.from_dict(data)):
                await self._inner.delete(user_hash)
                removed += 1
        return removed


class ModalDictSessionStore:
    """Sessions in a `modal.Dict`, shared by all containers. Values are plain dicts, not pickled classes."""

    def __init__(self, modal_dict: Any) -> None:
        self._dict = modal_dict

    async def get(self, user_hash: str) -> Session:
        return Session.from_dict(await self._dict.get.aio(user_hash))

    async def put(self, user_hash: str, session: Session) -> None:
        await self._dict.put.aio(user_hash, asdict(session))

    async def delete(self, user_hash: str) -> None:
        try:
            await self._dict.pop.aio(user_hash)
        except KeyError:
            pass


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
    llm_status: LlmStatus | None = None  # None when the LLM was not called this turn
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
    "llm_status",
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


# ---------------------------------------------------------------- anonymous decline counter


class DeclineCounter(Protocol):
    """Counts declined consents per WAT day. No hash, session or text: just (date, declines)."""

    async def increment(self) -> None: ...


def today_wat() -> str:
    return datetime.now(WAT).date().isoformat()


class MemoryDeclineCounter:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def increment(self) -> None:
        day = today_wat()
        self.counts[day] = self.counts.get(day, 0) + 1


class ModalDictDeclineCounter:
    """Counts in their own `modal.Dict`, keyed "YYYY-MM-DD". Read-then-write: a rare lost increment
    under concurrent declines is acceptable for a summary statistic."""

    def __init__(self, modal_dict: Any) -> None:
        self._dict = modal_dict

    async def increment(self) -> None:
        day = today_wat()
        current = await self._dict.get.aio(day) or 0
        await self._dict.put.aio(day, int(current) + 1)


# ---------------------------------------------------------------- Postcode API data canary

CanaryStatus = Literal["valid", "not_found", "auth", "error"]


class CanaryStore(Protocol):
    """Daily canary results, next to the decline counter: {"YYYY-MM-DD": {status: count, "last": status}}."""

    async def record(self, status: CanaryStatus) -> None: ...


def _add_canary(day: dict[str, Any] | None, status: CanaryStatus) -> dict[str, Any]:
    day = dict(day or {})
    day[status] = int(day.get(status, 0)) + 1
    day["last"] = status
    day["last_ts"] = now_wat()
    return day


class MemoryCanaryStore:
    def __init__(self) -> None:
        self.days: dict[str, dict[str, Any]] = {}

    async def record(self, status: CanaryStatus) -> None:
        day = today_wat()
        self.days[day] = _add_canary(self.days.get(day), status)


class ModalDictCanaryStore:
    """Canary results in their own `modal.Dict`, keyed "YYYY-MM-DD" (WAT). Read-then-write, like declines."""

    def __init__(self, modal_dict: Any) -> None:
        self._dict = modal_dict

    async def record(self, status: CanaryStatus) -> None:
        day = today_wat()
        await self._dict.put.aio(day, _add_canary(await self._dict.get.aio(day), status))


class CanaryReader(Protocol):
    """Today's last canary result ("valid", "not_found", "auth", "error") or None if unknown."""

    async def today(self) -> CanaryStatus | None: ...


class MemoryCanaryReader:
    def __init__(self, status: CanaryStatus | None = None) -> None:
        self.status = status

    async def today(self) -> CanaryStatus | None:
        return self.status


class ModalDictCanaryReader:
    """Reads today's entry of the canary Dict, cached for `cache_s` so code checks stay fast."""

    def __init__(
        self, modal_dict: Any, cache_s: float = 60.0, clock: Callable[[], float] = time.time
    ) -> None:
        self._dict = modal_dict
        self._cache_s = cache_s
        self._clock = clock
        self._at = -cache_s
        self._value: CanaryStatus | None = None

    async def today(self) -> CanaryStatus | None:
        if self._clock() - self._at >= self._cache_s:
            day = await self._dict.get.aio(today_wat()) or {}
            self._value = day.get("last")
            self._at = self._clock()
        return self._value
