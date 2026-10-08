"""Scrub personal data from text before it is stored (hard rule 4).

Use the raw text inside the turn (postcode regex, intent); store only `scrub(text)`. Names are not
redacted (no reliable way to find them), so stored text is also capped at TRANSCRIPT_CAP characters.
"""

import re

from app.services.postcode import POSTCODE_RE

TRANSCRIPT_CAP = 300

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Nigerian phones: +234 or 234 then 10 digits, or 0 + [789][01] + 8 digits. Spaces/dashes allowed.
_PHONE_RE = re.compile(r"(?:\+?234[\s-]?[789][01]|\b0[789][01])(?:[\s-]?\d){8}\b")
# Any other run of 7+ digits (NIN 11, BVN 11, account numbers 10), spaces/dashes allowed between digits.
_NUMBER_RE = re.compile(r"\d(?:[\s-]?\d){6,}")
_SLOT = "\x00{}\x00"


def scrub(text: str | None) -> str | None:
    if text is None:
        return None
    kept: list[str] = []

    def keep(match: re.Match[str]) -> str:
        kept.append(match.group(0))
        return _SLOT.format(len(kept) - 1)

    out = POSTCODE_RE.sub(keep, text)  # postcodes are public, not personal: keep them as said
    out = _EMAIL_RE.sub("[EMAIL]", out)
    out = _PHONE_RE.sub("[PHONE]", out)
    out = _NUMBER_RE.sub("[NUMBER]", out)
    for i, original in enumerate(kept):
        out = out.replace(_SLOT.format(i), original)
    return out


def for_storage(text: str | None) -> str | None:
    """Scrubbed and capped: the only form of user text that may enter a LogRow or a session."""
    cleaned = scrub(text)
    if cleaned is None:
        return None
    cleaned = cleaned.strip()[:TRANSCRIPT_CAP]
    return cleaned or None
