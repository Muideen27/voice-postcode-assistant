"""Review sheet round trip: write CSV -> reviewer fills it -> apply back into the template JSON."""

import csv
import json
import shutil
from pathlib import Path

import pytest

from scripts.apply_review import apply_review
from scripts.review_sheet import COLUMNS, split_fact_sheet, write_sheet

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def templates(tmp_path: Path) -> Path:
    out = tmp_path / "templates"
    shutil.copytree(ROOT / "app" / "templates", out)
    return out


@pytest.fixture
def data(tmp_path: Path) -> Path:
    out = tmp_path / "data"
    shutil.copytree(ROOT / "data", out)
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
def test_sheet_has_one_row_per_review_key_plus_fact_sheet(
    lang: str, templates: Path, data: Path, tmp_path: Path
) -> None:
    path, count = write_sheet(lang, templates, tmp_path / "review", data)
    rows = read_rows(path)
    todo = json.loads((templates / f"{lang}.json").read_text(encoding="utf-8"))["_todo_review"]
    assert count == len(rows) == len(todo) + 1
    assert [r["key"] for r in rows] == [*todo, "fact_sheet"]
    assert rows[-1]["draft"].startswith("# ")
    assert all(r["reviewer_text"] == "" for r in rows)
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")  # BOM for spreadsheet apps


def test_apply_writes_text_and_clears_review_keys(templates: Path, data: Path, tmp_path: Path) -> None:
    path, _ = write_sheet("yo", templates, tmp_path / "review", data)
    rows = read_rows(path)
    by_key = {r["key"]: r for r in rows}
    by_key["thanks"]["reviewer_text"] = "Ẹ ṣé gan-an fún èsì yín!"
    by_key["postcode_result"]["reviewer_text"] = "Pósíkòdì yín ni {display}."
    write_rows(path, rows)

    applied, errors = apply_review("yo", path, templates, data)

    yo = json.loads((templates / "yo.json").read_text(encoding="utf-8"))
    assert sorted(applied) == ["postcode_result", "thanks"] and errors == []
    assert yo["thanks"] == "Ẹ ṣé gan-an fún èsì yín!"
    assert "thanks" not in yo["_todo_review"] and "postcode_result" not in yo["_todo_review"]
    assert "welcome" in yo["_todo_review"]  # untouched rows stay pending
    assert split_fact_sheet((data / "fact_sheet_yo.md").read_text(encoding="utf-8"))[0] == "pending"


def test_apply_rejects_wrong_placeholders_and_unknown_keys(
    templates: Path, data: Path, tmp_path: Path
) -> None:
    path, _ = write_sheet("ha", templates, tmp_path / "review", data)
    rows = read_rows(path)
    by_key = {r["key"]: r for r in rows}
    original = json.loads((templates / "ha.json").read_text(encoding="utf-8"))
    by_key["postcode_result"]["reviewer_text"] = "Postcode ɗinka ita ce {lambar}."  # renamed placeholder
    by_key["we_heard"]["reviewer_text"] = "Abin da muka ji: {transcript"  # broken brace
    rows.append({"key": "made_up", "english": "", "draft": "", "reviewer_text": "x", "notes": ""})
    write_rows(path, rows)

    applied, errors = apply_review("ha", path, templates, data)

    ha = json.loads((templates / "ha.json").read_text(encoding="utf-8"))
    assert applied == [] and len(errors) == 3
    assert ha["postcode_result"] == original["postcode_result"]
    assert "postcode_result" in ha["_todo_review"]


def test_apply_fact_sheet_marks_it_done(templates: Path, data: Path, tmp_path: Path) -> None:
    path, _ = write_sheet("ig", templates, tmp_path / "review", data)
    rows = read_rows(path)
    reviewed = rows[-1]["draft"].replace("Postcode ọhụrụ gị", "Postcode ọhụrụ gị (reviewed)")
    rows[-1]["reviewer_text"] = reviewed
    write_rows(path, rows)

    applied, errors = apply_review("ig", path, templates, data)

    assert (applied, errors) == (["fact_sheet"], [])
    status, body = split_fact_sheet((data / "fact_sheet_ig.md").read_text(encoding="utf-8"))
    assert (status, body) == ("done", reviewed.strip())
    assert write_sheet("ig", templates, tmp_path / "review2", data)[1] == len(rows) - 1  # no fact_sheet row


def test_apply_fact_sheet_rejects_changed_codes(templates: Path, data: Path, tmp_path: Path) -> None:
    path, _ = write_sheet("yo", templates, tmp_path / "review", data)
    rows = read_rows(path)
    rows[-1]["reviewer_text"] = rows[-1]["draft"].replace("LA-11-A12-GN-01", "OG-02-B11-AA-07")
    write_rows(path, rows)

    applied, errors = apply_review("yo", path, templates, data)

    assert applied == [] and len(errors) == 1
    assert split_fact_sheet((data / "fact_sheet_yo.md").read_text(encoding="utf-8"))[0] == "pending"
