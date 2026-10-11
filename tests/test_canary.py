"""Postcode API data canary with fake services."""

import asyncio
import json

import pytest

from app.canary import CANARY_CODE, run_canary
from app.services.postcode import LookupResult, PostcodeError
from app.store import MemoryCanaryStore, today_wat


class FakePostcode:
    def __init__(self, outcome: LookupResult | Exception) -> None:
        self.outcome = outcome
        self.codes: list[str] = []

    async def lookup(self, code: str) -> LookupResult:
        self.codes.append(code)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


@pytest.mark.parametrize(
    ("outcome", "status"),
    [
        (LookupResult(CANARY_CODE, True, "valid"), "valid"),
        (LookupResult(CANARY_CODE, False, "not_found"), "not_found"),
        (PostcodeError("auth", code="invalid_api_key"), "auth"),
        (PostcodeError("timeout"), "error"),
        (RuntimeError("boom"), "error"),
    ],
)
def test_canary_statuses(outcome: object, status: str, capsys: pytest.CaptureFixture[str]) -> None:
    fake, store = FakePostcode(outcome), MemoryCanaryStore()  # type: ignore[arg-type]
    assert asyncio.run(run_canary(fake, store)) == status
    assert fake.codes == [CANARY_CODE]
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["canary"] == status and line["ts"].endswith("+01:00")
    day = store.days[today_wat()]
    assert (day[status], day["last"]) == (1, status)


def test_canary_counts_accumulate_per_day() -> None:
    store = MemoryCanaryStore()
    asyncio.run(run_canary(FakePostcode(LookupResult(CANARY_CODE, False, "not_found")), store))
    asyncio.run(run_canary(FakePostcode(LookupResult(CANARY_CODE, True, "valid")), store))
    day = store.days[today_wat()]
    assert (day["not_found"], day["valid"], day["last"]) == (1, 1, "valid")


def test_canary_store_failure_is_harmless() -> None:
    class Broken(MemoryCanaryStore):
        async def record(self, status: str) -> None:  # type: ignore[override]
            raise ConnectionError("dict down")

    assert (
        asyncio.run(run_canary(FakePostcode(LookupResult(CANARY_CODE, True, "valid")), Broken())) == "valid"
    )


def test_canary_times_out_as_error() -> None:
    class Slow(FakePostcode):
        async def lookup(self, code: str) -> LookupResult:
            await asyncio.sleep(5)
            return LookupResult(code, True, "valid")

    store = MemoryCanaryStore()
    assert (
        asyncio.run(run_canary(Slow(LookupResult(CANARY_CODE, True, "valid")), store, timeout_s=0.05))
        == "error"
    )
