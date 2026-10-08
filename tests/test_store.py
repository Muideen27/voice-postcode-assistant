"""Store tests: hashing, sessions, interaction log. No network, no Modal."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from app.store import (
    SCHEMA_FIELDS,
    JsonlLog,
    Latency,
    LogRow,
    MemoryLog,
    MemorySessionStore,
    ModalDictSessionStore,
    Session,
    hash_user,
    now_wat,
)

SESSION_ID = "6f1c2b8e-0d3a-4e55-9a7b-2c1d0e9f8a11"
USER = hash_user("salt", "web", SESSION_ID)


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- hashing


def test_hash_is_stable_hex_and_hides_the_id() -> None:
    assert USER == hash_user("salt", "web", SESSION_ID)
    assert len(USER) == 64 and int(USER, 16) >= 0
    assert SESSION_ID not in USER


def test_hash_depends_on_salt() -> None:
    assert hash_user("other-salt", "web", SESSION_ID) != USER


@pytest.mark.parametrize(("salt", "sid"), [("", SESSION_ID), ("salt", "")])
def test_hash_rejects_empty_inputs(salt: str, sid: str) -> None:
    with pytest.raises(ValueError):
        hash_user(salt, "web", sid)


# ---------------------------------------------------------------- sessions


def test_memory_store_new_user_gets_defaults() -> None:
    assert run(MemorySessionStore().get(USER)) == Session()


def test_memory_store_round_trip() -> None:
    store = MemorySessionStore()
    session = Session(lang="yo", consented=True, knew_before_asked=True, awaiting="feedback", turns=3)
    run(store.put(USER, session))
    assert run(store.get(USER)) == session


def test_session_ignores_unknown_fields_from_older_versions() -> None:
    assert Session.from_dict({"lang": "ha", "old_field": 1}) == Session(lang="ha")


class FakeModalDict:
    """Mimics the `.get.aio` / `.put.aio` interface of modal.Dict."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        outer = self

        class _Get:
            async def aio(self, key: str) -> Any:
                return outer.data.get(key)

        class _Put:
            async def aio(self, key: str, value: Any) -> None:
                outer.data[key] = value

        self.get = _Get()
        self.put = _Put()


def test_modal_dict_store_stores_plain_dicts() -> None:
    fake = FakeModalDict()
    store = ModalDictSessionStore(fake)
    run(store.put(USER, Session(lang="ig", consented=True)))
    assert isinstance(fake.data[USER], dict)
    assert run(store.get(USER)) == Session(lang="ig", consented=True)
    assert run(store.get("missing")) == Session()


# ---------------------------------------------------------------- log rows


def make_row(**overrides: Any) -> LogRow:
    values: dict[str, Any] = dict(
        user_hash=USER,
        lang="yo",
        input="voice",
        reply_kind="ask_location",
        transcript="ẹjọ́, mo fẹ́ mọ pósíkòdì ilé mi",
        intent="get_my_postcode",
        latency_ms=Latency(asr=2400, llm=2100, total=4700),
        ts="2026-10-10T14:52:03+01:00",
    )
    values.update(overrides)
    return LogRow(**values)


def test_row_json_matches_schema_exactly() -> None:
    row = json.loads(make_row().to_json())
    assert tuple(row) == SCHEMA_FIELDS
    assert row["channel"] == "web"
    assert row["latency_ms"] == {"asr": 2400, "llm": 2100, "api": None, "total": 4700}
    assert row["transcript"] == "ẹjọ́, mo fẹ́ mọ pósíkòdì ilé mi"  # stored as UTF-8, not escaped


def test_row_has_no_place_for_private_data() -> None:
    forbidden = {"lat", "lng", "latitude", "longitude", "audio", "session", "session_id", "phone"}
    assert forbidden.isdisjoint(SCHEMA_FIELDS)
    with pytest.raises(TypeError):
        LogRow(user_hash=USER, lang="en", input="location", reply_kind="postcode", lat=6.6)  # type: ignore[call-arg]


@pytest.mark.parametrize("bad", [SESSION_ID, "abc", USER.upper(), "+2348012345678"])
def test_row_rejects_raw_ids(bad: str) -> None:
    with pytest.raises(ValueError):
        make_row(user_hash=bad)


def test_now_wat_has_plus_one_offset() -> None:
    assert now_wat().endswith("+01:00")


# ---------------------------------------------------------------- log sinks


def test_memory_log_collects_rows() -> None:
    log = MemoryLog()
    run(log.append(make_row()))
    assert len(log.rows) == 1


def test_jsonl_log_appends_one_line_per_turn_per_day(tmp_path: Path) -> None:
    log = JsonlLog(tmp_path)
    run(log.append(make_row()))
    run(log.append(make_row(input="location", reply_kind="postcode", postcode_found=True, api_status="ok")))
    run(log.append(make_row(ts="2026-10-11T09:00:00+01:00", feedback="yes", reply_kind="thanks")))

    day1 = (tmp_path / "interactions-2026-10-10.jsonl").read_text(encoding="utf-8").splitlines()
    day2 = (tmp_path / "interactions-2026-10-11.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(day1) == 2 and len(day2) == 1
    assert json.loads(day1[1])["postcode_found"] is True
    assert json.loads(day2[0])["feedback"] == "yes"


def test_jsonl_log_uses_container_suffix_and_commits(tmp_path: Path) -> None:
    commits = 0

    async def commit() -> None:
        nonlocal commits
        commits += 1

    log = JsonlLog(tmp_path / "logs", suffix="ta-123", commit=commit)
    run(log.append(make_row()))
    assert (tmp_path / "logs" / "interactions-2026-10-10-ta-123.jsonl").exists()
    assert commits == 1
