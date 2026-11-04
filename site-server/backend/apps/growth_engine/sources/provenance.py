"""Field-level provenance helpers.

A *source ref* is a short string saying where a value came from:

    manual                      typed by a person in the panel
    csv:<file>:<row>            a row of an imported CSV (row = spreadsheet row number)
    extract:<run id>            read from the lead's own website by an extraction run
    osm:<node|way|relation>/<id>  an OpenStreetMap object found by a discovery job (© OpenStreetMap contributors, ODbL)
    search:<provider>:<host>    a result of a search-API discovery job

``Lead.provenance`` maps each field to ``{"source": <ref>, "at": <iso time>, "by": <user id | null>}``.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

MANUAL = "manual"


def csv_ref(file_name: str, row_number: int) -> str:
    safe = re.sub(r"[:\x00-\x1f]", "_", file_name or "file.csv").strip()[:120] or "file.csv"
    return f"csv:{safe}:{row_number}"


def extract_ref(run_id: int) -> str:
    return f"extract:{run_id}"


def osm_ref(osm_type: str, osm_id) -> str:
    return f"osm:{osm_type}/{osm_id}"


def search_ref(provider: str, host: str) -> str:
    return f"search:{provider}:{(host or '')[:150]}"


def parse_ref(ref: str) -> dict:
    """{'kind': 'manual'|'csv'|'extract'|'osm'|'search'|'other', 'file', 'row', 'run'} - for display."""
    if not ref or ref == MANUAL:
        return {"kind": "manual"}
    if ref.startswith("csv:"):
        _, _, rest = ref.partition(":")
        file_name, _, row = rest.rpartition(":")
        return {"kind": "csv", "file": file_name, "row": int(row) if row.isdigit() else None}
    if ref.startswith("osm:"):
        obj = ref.split(":", 1)[1]
        return {"kind": "osm", "object": obj, "url": f"https://www.openstreetmap.org/{obj}"}
    if ref.startswith("search:"):
        _, _, rest = ref.partition(":")
        provider, _, host = rest.partition(":")
        return {"kind": "search", "provider": provider, "host": host}
    if ref.startswith("extract:"):
        run = ref.split(":", 1)[1]
        return {"kind": "extract", "run": int(run) if run.isdigit() else None}
    return {"kind": "other", "ref": ref}


def stamp(provenance: dict, field: str, source_ref: str, actor_id: int | None = None) -> dict:
    """Record that ``field`` now comes from ``source_ref``. Mutates and returns ``provenance``."""
    provenance[field] = {"source": source_ref or MANUAL, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "by": actor_id}
    return provenance
