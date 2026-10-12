"""Pilot dashboard numbers from a fixture log: real-data rules, empty state, no transcript or user hash."""

import json
from pathlib import Path

from app.stats import compute_stats, load_rows
from app.store import Latency, LogRow, hash_user, today_wat

A, B, C = (hash_user("salt", "web", f"user-{i}") for i in range(3))
PILOT = "2026-10-10T09:00:00+01:00"


def row(ts: str, user: str, **kw) -> str:
    return LogRow(
        user_hash=user, **{"lang": "yo", "input": "text", "reply_kind": "menu", "ts": ts, **kw}
    ).to_json()


def logs(tmp: Path) -> Path:
    d = tmp / "logs"
    (d / "dev").mkdir(parents=True)
    lines = [
        row("2026-10-10T08:00:00+01:00", A, input="location", postcode_found=True),  # before the pilot
        row("2026-10-10T09:00:00+01:00", A, input="choice", knew_postcode_before=False),
        row(
            "2026-10-10T09:01:00+01:00",
            A,
            input="location",
            postcode_found=False,
            api_status="not_found",
            latency_ms=Latency(api=700, total=900),
        ),  # fmt: skip
        row("2026-10-10T09:02:00+01:00", A, input="choice", reply_kind="thanks", feedback="yes"),
        row(
            "2026-10-10T09:03:00+01:00",
            B,
            lang="ha",
            input="voice",
            intent="get_my_postcode",
            transcript="ina son sanin postcode",
            latency_ms=Latency(asr=2000, llm=2500, total=4600),
        ),  # fmt: skip
        row(
            "2026-10-10T09:04:00+01:00",
            B,
            lang="ha",
            input="text",
            intent="validate_postcode",
            postcode_found=True,
            transcript="LA 11 A12 GN 01",
            latency_ms=Latency(api=600, total=700),
        ),  # fmt: skip
        row("2026-10-10T09:05:00+01:00", B, lang="ha", input="choice", feedback="no"),
        row("2026-10-10T09:06:00+01:00", C, lang="en", input="choice", knew_postcode_before=True),
        row(
            "2026-10-10T09:07:00+01:00",
            C,
            lang="en",
            input="text",
            intent="explain_postcode",
            transcript="what is it",
        ),
        row("2026-10-10T09:08:00+01:00", C, lang="en", input="location", api_status="auth:invalid_api_key"),
    ]
    (d / "interactions-2026-10-10-ta-1.jsonl").write_text("\n".join(lines) + "\n")
    (d / "dev" / "interactions-2026-10-10-ta-9.jsonl").write_text(row("2026-10-10T09:30:00+01:00", C) + "\n")
    return d


def test_dashboard_numbers_from_pilot_rows_only(tmp_path: Path) -> None:
    rows, _ = load_rows(logs(tmp_path), since=PILOT)
    canary = {today_wat(): {"not_found": 3, "last": "not_found"}}
    s = compute_stats(rows, canary, PILOT)

    assert s["kpis"] == {
        "interactions": 9,  # the 08:00 row is before PILOT_START; dev/ is never read
        "content_turns": 5,
        "valid_postcode_pct": 33,  # 1 valid of 3 location/validate turns
        "valid_postcode_n": 3,
        "did_not_know_pct": 50,
        "did_not_know_n": 2,
        "helped_pct": 50,
        "helped_n": 2,
    }
    assert {d["label"]: d["value"] for d in s["by_language"]} == {
        "Yorùbá": 3,
        "Hausa": 3,
        "English": 3,
        "Igbo": 0,
    }
    assert {d["label"]: d["pct"] for d in s["helped_by_language"]} == {
        "Yorùbá": 100,
        "Hausa": 0,
        "English": None,
        "Igbo": None,
    }
    assert {d["label"]: d["value"] for d in s["asked_for"]} == {
        "My postcode": 1,
        "Explain it": 1,
        "Check a code": 1,
        "Other": 0,
    }
    assert {d["label"]: d["value"] for d in s["median_seconds"]} == {"Location": 0.9, "Voice": 4.6}
    assert s["canary_today"] == "no data"
    assert [r["postcode"] for r in s["recent"][:3]] == ["Error", "—", "—"]
    assert len(s["recent"]) == 9 and s["recent"][0]["time"].endswith("09:08")


def test_empty_state_before_the_pilot(tmp_path: Path) -> None:
    s = compute_stats([], {}, None)
    assert s["kpis"]["interactions"] == 0
    assert s["kpis"]["valid_postcode_pct"] is None and s["kpis"]["helped_pct"] is None
    assert s["recent"] == [] and s["canary_today"] == "—"
    assert all(d["value"] == 0 for d in s["by_language"])


def test_response_never_contains_transcripts_or_user_hashes(tmp_path: Path) -> None:
    rows, _ = load_rows(logs(tmp_path), since=PILOT)
    text = json.dumps(compute_stats(rows, {}, PILOT), ensure_ascii=False)
    for secret in (
        A,
        B,
        C,
        "ina son sanin postcode",
        "what is it",
        "LA 11 A12 GN 01",
        "transcript",
        "user_hash",
    ):
        assert secret not in text


def test_canary_status_words() -> None:
    day = today_wat()
    assert compute_stats([], {day: {"last": "valid"}}, None)["canary_today"] == "OK"
    assert compute_stats([], {day: {"last": "auth"}}, None)["canary_today"] == "unreachable"
    assert compute_stats([], {day: {"last": "error"}}, None)["canary_today"] == "unreachable"


def test_excluded_developer_sessions_never_count(tmp_path: Path) -> None:
    from app.stats import load_excluded

    excluded = tmp_path / "excluded_hashes.txt"
    excluded.write_text(f"# developer tests\n{B}  # smoke test\n\n")
    assert load_excluded(excluded) == {B}
    assert load_excluded(tmp_path / "missing.txt") == set()

    rows, info = load_rows(logs(tmp_path), since=PILOT, exclude=load_excluded(excluded))
    s = compute_stats(rows, {}, PILOT)
    assert info["excluded"] == 3 and s["kpis"]["interactions"] == 6
    assert {d["label"]: d["value"] for d in s["by_language"]}["Hausa"] == 0
    assert B not in json.dumps(s)


def test_default_pilot_start_is_sunday_midnight_wat() -> None:
    from app.stats import DEFAULT_PILOT_START, parse_ts

    assert DEFAULT_PILOT_START == "2026-10-11T00:00:00+01:00"
    assert parse_ts(DEFAULT_PILOT_START).utcoffset().total_seconds() == 3600
