"""export_log: merge, sort, dedupe and summarise a fixture log (two containers, a dev folder, bad lines)."""

import csv
from pathlib import Path

from app.store import Latency, LogRow, hash_user
from scripts.export_log import CSV_COLUMNS, export, load_rows, percentile

A, B, C = (hash_user("salt", "web", f"user-{i}") for i in range(3))


def row(ts: str, user: str, **kw) -> str:
    base = {"lang": "yo", "input": "text", "reply_kind": "menu", "ts": ts}
    return LogRow(user_hash=user, **{**base, **kw}).to_json()


def write_logs(tmp: Path) -> Path:
    logs = tmp / "logs"
    (logs / "dev").mkdir(parents=True)
    (logs / "interactions-2026-10-10-ta-1.jsonl").write_text(
        "\n".join(
            [
                row(
                    "2026-10-10T09:00:00+01:00",
                    A,
                    input="choice",
                    reply_kind="menu",
                    knew_postcode_before=False,
                ),
                row(
                    "2026-10-10T09:01:00+01:00",
                    A,
                    input="location",
                    reply_kind="error",
                    postcode_found=None,
                    api_status="not_found",
                    latency_ms=Latency(api=800, total=950),
                ),  # fmt: skip
                row("2026-10-10T09:02:00+01:00", A, input="choice", reply_kind="thanks", feedback="yes"),
                "{not json",
            ]
        )
        + "\n"
    )
    (logs / "interactions-2026-10-10-ta-2.jsonl").write_text(
        "\n".join(
            [
                row(
                    "2026-10-10T09:01:00+01:00",
                    A,
                    input="location",
                    reply_kind="error",  # duplicate of ta-1
                    api_status="not_found",
                    latency_ms=Latency(api=800, total=950),
                ),  # fmt: skip
                row(
                    "2026-10-10T08:30:00+01:00",
                    B,
                    lang="ha",
                    input="voice",
                    intent="explain_postcode",
                    llm_status="ok",
                    reply_kind="faq_parts",
                    transcript="menene ma'anar postcode",
                    latency_ms=Latency(asr=2400, llm=2600, total=5100),
                ),  # fmt: skip
                row(
                    "2026-10-10T08:31:00+01:00",
                    B,
                    lang="ha",
                    input="choice",
                    reply_kind="thanks",
                    feedback="no",
                ),
            ]
        )
        + "\n"
    )
    (logs / "interactions-2026-10-11-ta-3.jsonl").write_text(
        row("2026-10-11T10:00:00+01:00", C, lang="en", input="choice", knew_postcode_before=True) + "\n"
    )
    (logs / "dev" / "interactions-2026-10-10-ta-9.jsonl").write_text(
        row("2026-10-10T07:00:00+01:00", C) + "\n"
    )
    return logs


def test_load_merges_sorts_dedupes_and_ignores_dev(tmp_path: Path) -> None:
    rows, stats = load_rows(write_logs(tmp_path))
    assert [r["ts"][11:16] for r in rows] == ["08:30", "08:31", "09:00", "09:01", "09:02", "10:00"]
    assert (stats["files"], stats["duplicates"], stats["broken"]) == (3, 1, 1)
    assert not any(r["ts"].endswith("07:00:00+01:00") for r in rows)  # dev turn excluded


def test_since_filter(tmp_path: Path) -> None:
    rows, stats = load_rows(write_logs(tmp_path), since="2026-10-10T09:00:00+01:00")
    assert len(rows) == 4 and stats["before_since"] == 2


def test_export_writes_csv_and_summary(tmp_path: Path) -> None:
    declines = {"2026-10-10": 2, "2026-10-11": 1}
    canary = {
        "2026-10-10": {"not_found": 20, "last": "not_found"},
        "2026-10-11": {"valid": 3, "not_found": 1, "last": "valid"},
    }
    csv_path, md_path = export(write_logs(tmp_path), declines, canary, tmp_path / "out")

    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        table = list(csv.DictReader(f))
    assert tuple(table[0]) == CSV_COLUMNS and len(table) == 6
    assert table[0]["latency_asr_ms"] == "2400" and table[0]["transcript"] == "menene ma'anar postcode"
    assert not {"lat", "lng", "latitude", "longitude", "session", "session_id", "audio"} & set(CSV_COLUMNS)

    md = md_path.read_text(encoding="utf-8")
    for expected in (
        "| Interactions (logged turns after consent) | 6 |",
        "| Unique users (salted hashes) | 3 |",
        "| Content turns (voice, text, location) | 2 |",
        "| Feedback yes / no | 1 / 1 |",
        "| Knew their postcode before: yes / no / skipped or not asked | 1 / 1 / 1 |",
        "| Declined consent (anonymous count) | 3 |",
        "| 2026-10-10 | 0 | 20 | 0 | 0 | not_found | no (official data returned nothing) |",
        "| 2026-10-11 | 3 | 1 | 0 | 0 | valid | yes |",
        "| asr | 1 | 2400 | 2400 |",
        "| explain_postcode | 1 |",
    ):
        assert expected in md, expected


def test_percentile_nearest_rank() -> None:
    assert percentile([], 50) is None
    assert percentile([5, 1, 3], 50) == 3
    assert percentile(list(range(1, 101)), 95) == 95
