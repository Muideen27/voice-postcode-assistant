"""Record live Postcode API responses into tests/fixtures/postcode/ (replaces the reconstructed ones).

Usage:
    POSTCODE_API_KEY=nipost_test_... python scripts/record_postcode_fixtures.py

Then rerun `pytest -q`; if a shape changed, fix app/services/postcode.py and SPEC.md §3.6 together.
"""

import json
import os
from pathlib import Path

import httpx

BASE = "https://api.postcode.gov.ng"
OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "postcode"

# Ikeja (known valid), the Atlantic off Lagos (expected: nothing within 250 m), a valid and an invalid
# code, and a level our L1 key does not have.
CALLS = {
    "reverse_found.json": ("/v1/search/reverse", {"lat": 6.6018, "lng": 3.3515, "max_distance_m": 250}),
    "reverse_not_found.json": ("/v1/search/reverse", {"lat": 6.2, "lng": 3.4, "max_distance_m": 250}),
    "lookup_valid.json": ("/v1/lookup", {"code": "LA-11-A12-GN-01", "level": 1}),
    "lookup_not_found.json": ("/v1/lookup", {"code": "LA-11-W06-TC-10", "level": 1}),
    "error_level_not_granted.json": ("/v1/lookup", {"code": "LA-11-A12-GN-01", "level": 2}),
}
NO_KEY_CALL = ("error_auth_required.json", "/v1/lookup", {"code": "LA-11-A12-GN-01", "level": 1})


def save(name: str, response: httpx.Response) -> None:
    # The HTTP status is printed, not stored: fixtures hold the body only. Note new statuses in the README.
    print(f"{response.status_code}  {name}  {response.text[:200]}")
    (OUT / name).write_text(json.dumps(response.json(), ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    headers = {"X-API-Key": os.environ["POSTCODE_API_KEY"]}
    with httpx.Client(base_url=BASE, headers=headers, timeout=10) as http:
        for name, (path, params) in CALLS.items():
            save(name, http.get(path, params=params))
    name, path, params = NO_KEY_CALL
    with httpx.Client(base_url=BASE, timeout=10) as http:
        save(name, http.get(path, params=params))


if __name__ == "__main__":
    main()
