# Postcode API fixtures

Response bodies used by `tests/test_postcode.py` (served through `httpx.MockTransport`, no network).

| File | Request | Source |
|---|---|---|
| `reverse_found.json` | `GET /v1/search/reverse?lat=6.6018&lng=3.3515&max_distance_m=250` → 200 | **live**, 3 Oct 2026, test key |
| `lookup_valid.json` | `GET /v1/lookup?code=LA-11-A12-GN-01&level=1` → 200 | **live**, 3 Oct 2026 |
| `lookup_not_found.json` | `GET /v1/lookup?code=LA-11-W06-TC-10&level=1` → 200 | **live**, 3 Oct 2026 |
| `error_level_not_granted.json` | `GET /v1/lookup?code=LA-11-A12-GN-01&level=2` | **live** body, 3 Oct 2026 (HTTP status not recorded) |
| `error_auth_required.json` | any endpoint without `X-API-Key` | **live** body, 3 Oct 2026 (HTTP status not recorded) |
| `reverse_not_found.json` | reverse with nothing in range | reconstructed (`found:false` + `radius_m`); no live capture yet |

Live 200s carry `x-ratelimit-limit: 600` and `x-ratelimit-remaining` headers.

Re-record: `POSTCODE_API_KEY=... python scripts/record_postcode_fixtures.py`, then `pytest -q`.
