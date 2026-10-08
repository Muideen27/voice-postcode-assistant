"""Template files: same keys and placeholders in every language, licence text verbatim."""

import json
import string
from pathlib import Path

import pytest

from app.events import LANGS

TEMPLATES = Path(__file__).resolve().parents[1] / "app" / "templates"
ATTRIBUTION = (
    "N-ATLaS is an initiative of the Federal Ministry of Communications, Innovation and Digital Economy, "
    "and powered by Awarri Technologies."
)


def load(lang: str) -> dict:
    return json.loads((TEMPLATES / f"{lang}.json").read_text(encoding="utf-8"))


def strings(lang: str) -> dict[str, str]:
    return {k: v for k, v in load(lang).items() if not k.startswith("_")}


def placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_english_is_final() -> None:
    assert load("en")["_todo_review"] == []


@pytest.mark.parametrize("lang", LANGS)
def test_same_keys_as_english(lang: str) -> None:
    assert strings(lang).keys() == strings("en").keys()


@pytest.mark.parametrize("lang", LANGS)
def test_same_placeholders_as_english(lang: str) -> None:
    en = strings("en")
    for key, text in strings(lang).items():
        assert placeholders(text) == placeholders(en[key]), key


@pytest.mark.parametrize("lang", LANGS)
def test_strings_are_non_empty_and_short(lang: str) -> None:
    for key, text in strings(lang).items():
        assert text.strip(), key
        assert len(text) <= 600, key


@pytest.mark.parametrize("lang", LANGS)
def test_review_list_names_real_keys(lang: str) -> None:
    assert set(load(lang)["_todo_review"]) <= strings(lang).keys()


@pytest.mark.parametrize("lang", LANGS)
def test_attribution_is_verbatim(lang: str) -> None:
    assert strings(lang)["attribution"] == ATTRIBUTION


@pytest.mark.pilot
@pytest.mark.parametrize("lang", ["yo", "ha", "ig"])
def test_pilot_gate_all_strings_reviewed(lang: str) -> None:
    assert load(lang)["_todo_review"] == [], f"{lang}: native-speaker review still pending"
