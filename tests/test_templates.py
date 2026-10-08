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


def test_every_faq_id_has_a_template() -> None:
    from app.services.prompts import FAQ_IDS

    assert {k for k in strings("en") if k.startswith("faq_")} == {f"faq_{i}" for i in FAQ_IDS}


def test_english_faq_answers_are_at_most_60_words() -> None:
    for key, text in strings("en").items():
        if key.startswith("faq_"):
            assert len(text.split()) <= 60, key


@pytest.mark.parametrize("lang", LANGS)
def test_who_built_has_attribution_and_data_source(lang: str) -> None:
    text = strings(lang)["faq_who_built"]
    assert ATTRIBUTION in text and "Nigeria Postcode API" in text


@pytest.mark.parametrize("lang", LANGS)
def test_place_name_no_points_to_the_location_button(lang: str) -> None:
    t = strings(lang)
    assert f'"{t["btn_location"]}"' in t["faq_place_name_no"]
