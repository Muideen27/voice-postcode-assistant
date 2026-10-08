"""PII scrubbing before storage."""

import pytest

from app.privacy import TRANSCRIPT_CAP, for_storage, scrub


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("my NIN is 12345678901", "my NIN is [NUMBER]"),
        ("NIN 123 4567 8901 please", "NIN [NUMBER] please"),
        ("call me on 0803 123 4567", "call me on [PHONE]"),
        ("call me on 08031234567.", "call me on [PHONE]."),
        ("my number is +2348031234567", "my number is [PHONE]"),
        ("my number is +234 803 123 4567", "my number is [PHONE]"),
        ("write to ade.bayo+pc@mail.example.ng now", "write to [EMAIL] now"),
        ("account 0123-456-789", "account [NUMBER]"),
    ],
)
def test_scrub_replaces_personal_numbers_and_emails(text: str, expected: str) -> None:
    assert scrub(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "is LA-11-A12-GN-01 correct?",
        "is LA 11 A12 GN 01 correct?",
        "la11a12gn01",
        "ṣé pósíkòdì mi ni LA 11 A12 GN 01?",
        "house 12, street 4",  # short numbers stay
    ],
)
def test_scrub_keeps_postcodes_and_short_numbers(text: str) -> None:
    assert scrub(text) == text


def test_postcode_and_phone_together() -> None:
    assert scrub("LA 11 A12 GN 01, phone 0803 123 4567") == "LA 11 A12 GN 01, phone [PHONE]"


def test_for_storage_caps_and_handles_empty() -> None:
    assert for_storage(None) is None
    assert for_storage("   ") is None
    assert len(for_storage("a" * 1000) or "") == TRANSCRIPT_CAP
    assert for_storage(" NIN 12345678901 ") == "NIN [NUMBER]"
