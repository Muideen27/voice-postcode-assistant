"""fill_submission: placeholders filled from a real export of a fixture log; manual values; nothing invented."""

import json
from pathlib import Path

import scripts.fill_submission as fill
from scripts.export_log import export
from tests.test_export_log import write_logs


def test_fill_from_export(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "validation"
    export(
        write_logs(tmp_path), {"2026-10-10": 2}, {"2026-10-10": {"not_found": 4, "last": "not_found"}}, out
    )
    submission = tmp_path / "submission"
    submission.mkdir()
    (submission / "03_validation.md").write_text(
        "Interactions {{N_INTERACTIONS}}; users {{N_USERS}}; yes/no {{FEEDBACK_YES}}/{{FEEDBACK_NO}}; "
        "knew {{KNEW_YES}}/{{KNEW_NO}}/{{KNEW_SKIPPED}}; dates {{PILOT_DATES}}; testers {{N_TESTERS}}\n"
        "{{CHART_LANGUAGE}}\n{{TABLE_CANARY}}\n{{TABLE_RECENT}}\n"
    )
    (submission / "manual.json").write_text(json.dumps({"PILOT_DATES": "10-11 Oct 2026", "N_TESTERS": ""}))
    monkeypatch.setattr(fill, "SUMMARY", out / "summary.md")
    monkeypatch.setattr(fill, "INTERACTIONS", out / "interactions.csv")
    monkeypatch.setattr(fill, "SUBMISSION", submission)
    monkeypatch.setattr(fill, "BUILD", submission / "build")
    monkeypatch.setattr(fill, "MANUAL", submission / "manual.json")

    fill.main()
    text = (submission / "build" / "03_validation.md").read_text()

    assert "Interactions 6; users 3; yes/no 1/1; knew 1/1/1; dates 10-11 Oct 2026" in text
    assert "testers {{N_TESTERS}}" in text  # empty manual value stays visibly open
    assert '<div class="bars">' in text and "Yorùbá" in text
    assert "| 2026-10-10 | 0 | 4 | 0 | 0 | not_found |" in text
    assert "| Time | Language | Input | Intent | Postcode | Response | Feedback |" in text
    assert "menene" not in text  # recent-sessions table never shows transcripts
