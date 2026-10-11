"""Review sheet round trip: write CSV -> reviewer fills it -> apply back into the template JSON."""

import csv
import json
import shutil
from pathlib import Path

import pytest

from scripts.apply_review import apply_review
from scripts.review_sheet import COLUMNS, GROUPS, group_of, write_sheet

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def templates(tmp_path: Path) -> Path:
    out = tmp_path / "templates"
    shutil.copytree(ROOT / "app" / "templates", out)
    return out


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


@pytest.mark.parametrize("lang", ["yo", "ha", "ig"])
def test_three_sheets_split_the_review_keys(lang: str, templates: Path, tmp_path: Path) -> None:
    todo = json.loads((templates / f"{lang}.json").read_text(encoding="utf-8"))["_todo_review"]
    keys: dict[str, list[str]] = {}
    for group in GROUPS:
        path, count = write_sheet(lang, templates, tmp_path / "review", group=group)
        rows = read_rows(path)
        assert count == len(rows) and all(r["reviewer_text"] == "" for r in rows)
        assert path.read_bytes().startswith(b"\xef\xbb\xbf")  # BOM for spreadsheet apps
        keys[group] = [r["key"] for r in rows]
    assert sorted(sum(keys.values(), [])) == sorted(todo)  # every review key in exactly one sheet
    assert all(k.startswith("faq_") for k in keys["faq"]) and len(keys["faq"]) == 8
    assert all(k.startswith(("ui_", "conf_")) or k == "chip" for k in keys["ui"]) and len(keys["ui"]) == 24
    assert not any(group_of(k) != "main" for k in keys["main"])


def test_apply_writes_text_and_clears_review_keys(templates: Path, tmp_path: Path) -> None:
    path, _ = write_sheet("yo", templates, tmp_path / "review")
    rows = read_rows(path)
    by_key = {r["key"]: r for r in rows}
    by_key["thanks"]["reviewer_text"] = "Ẹ ṣé gan-an fún èsì yín!"
    by_key["postcode_result"]["reviewer_text"] = "Pósíkòdì yín ni {display}."
    write_rows(path, rows)

    applied, errors = apply_review("yo", path, templates)

    yo = json.loads((templates / "yo.json").read_text(encoding="utf-8"))
    assert sorted(applied) == ["postcode_result", "thanks"] and errors == []
    assert yo["thanks"] == "Ẹ ṣé gan-an fún èsì yín!"
    assert "thanks" not in yo["_todo_review"] and "postcode_result" not in yo["_todo_review"]
    assert "welcome" in yo["_todo_review"]  # untouched rows stay pending


def test_apply_faq_sheet(templates: Path, tmp_path: Path) -> None:
    path, _ = write_sheet("ig", templates, tmp_path / "review", group="faq")
    rows = read_rows(path)
    rows[0]["reviewer_text"] = rows[0]["draft"] + " (reviewed)"
    write_rows(path, rows)

    applied, errors = apply_review("ig", path, templates)

    ig = json.loads((templates / "ig.json").read_text(encoding="utf-8"))
    assert (applied, errors) == ([rows[0]["key"]], [])
    assert rows[0]["key"] not in ig["_todo_review"]


def test_apply_rejects_wrong_placeholders_and_unknown_keys(templates: Path, tmp_path: Path) -> None:
    path, _ = write_sheet("ha", templates, tmp_path / "review")
    rows = read_rows(path)
    by_key = {r["key"]: r for r in rows}
    original = json.loads((templates / "ha.json").read_text(encoding="utf-8"))
    by_key["postcode_result"]["reviewer_text"] = "Postcode ɗinka ita ce {lambar}."  # renamed placeholder
    by_key["we_heard"]["reviewer_text"] = "Abin da muka ji: {transcript"  # broken brace
    rows.append({"key": "made_up", "english": "", "draft": "", "reviewer_text": "x", "notes": ""})
    write_rows(path, rows)

    applied, errors = apply_review("ha", path, templates)

    ha = json.loads((templates / "ha.json").read_text(encoding="utf-8"))
    assert applied == [] and len(errors) == 3
    assert ha["postcode_result"] == original["postcode_result"]
    assert "postcode_result" in ha["_todo_review"]
