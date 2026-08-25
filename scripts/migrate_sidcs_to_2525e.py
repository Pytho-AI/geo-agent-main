#!/usr/bin/env python3
"""
One-time data migration: normalize every entity SIDC to 2525E numeric.

ONE symbol format lives in this system. The ingest boundary
(sync/create/update) normalizes new rows via app.utils.sidc; this
script converts what is already in PostGIS: legacy 2525C letter codes
from pre-standardization KG syncs and 2525D-era numerics (version 10).

Run inside the backend container (repo scripts/ is bind-mounted):

    docker exec geo-agent-backend-1 python3 /app/scripts/migrate_sidcs_to_2525e.py

Idempotent: rows already carrying a 20-digit version-13 SIDC are
untouched. Reports per-pattern counts and lists any SIDC it could not
convert (there must be none — unconverted formats may not linger
silently).
"""

import asyncio
import sys
from collections import Counter

sys.path.insert(0, "/app")

from sqlalchemy import select  # noqa: E402

from app.db.session import async_session  # noqa: E402
from app.models.entity import Entity  # noqa: E402
from app.utils.sidc import to_2525e_sidc  # noqa: E402


def _is_e(sidc: str) -> bool:
    return len(sidc) == 20 and sidc.isdigit() and sidc.startswith("13")


async def main() -> int:
    converted = Counter()
    unconvertible = Counter()
    scanned = 0
    changed = 0

    async with async_session() as db:
        result = await db.execute(select(Entity))
        rows = result.scalars().all()
        for entity in rows:
            attrs = entity.attrs or {}
            sidc = attrs.get("sidc")
            if not sidc:
                continue
            scanned += 1
            s = str(sidc).strip()
            if _is_e(s):
                continue
            new = to_2525e_sidc(s)
            if not new or not _is_e(new):
                unconvertible[s] += 1
                continue
            # New dict so SQLAlchemy's JSON change detection fires.
            entity.attrs = {**attrs, "sidc": new}
            key = s[:10] if s[0].isalpha() else f"v{s[:2]}-numeric"
            converted[key] += 1
            changed += 1
            if changed % 1000 == 0:
                await db.commit()
        await db.commit()

    print(f"scanned {scanned} sidc-bearing entities, converted {changed}")
    for pattern, n in converted.most_common():
        print(f"  {pattern}: {n}")
    if unconvertible:
        print("UNCONVERTIBLE — fix to_2525e_sidc and re-run:")
        for s, n in unconvertible.most_common():
            print(f"  {s!r}: {n}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
