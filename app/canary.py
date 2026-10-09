"""Postcode API data canary. Looks up the known code LA-11-A12-GN-01 (level 1) when a web container starts
and every 30 minutes, logs one JSON line and records the day's result, so the evidence shows on which days
the official data returned nothing (SPEC.md §3.6). It never touches users or the interaction log.
"""

import json

from app.services.interfaces import PostcodeService
from app.services.postcode import PostcodeError
from app.store import CanaryStatus, CanaryStore, now_wat

CANARY_CODE = "LA-11-A12-GN-01"  # valid on 3 Oct 2026 (reverse geocode of 6.6018, 3.3515)


async def check(postcode: PostcodeService) -> CanaryStatus:
    try:
        result = await postcode.lookup(CANARY_CODE)
    except PostcodeError as exc:
        return "auth" if exc.kind == "auth" else "error"
    except Exception:
        return "error"
    return "valid" if result.valid else "not_found"


async def run_canary(postcode: PostcodeService, store: CanaryStore) -> CanaryStatus:
    status = await check(postcode)
    print(json.dumps({"canary": status, "ts": now_wat()}))
    try:
        await store.record(status)
    except Exception as exc:  # the canary must never break a container start
        print(json.dumps({"event": "canary_store_error", "error": type(exc).__name__}))
    return status
