#!/usr/bin/env python3
"""Seed colección Mongo ``entities`` (DB01) — marcas/plataformas RalfIA."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from raphiia_openai import agent_auto_log, mongo_store  # noqa: E402
from raphiia_openai.settings import LINKEDIN_AUTHOR_URN  # noqa: E402

DEFAULT_ENTITIES = [
    {
        "entity_id": "ent_pcdoctor",
        "slug": "pc-doctor",
        "name": "PC Doctor S.A.",
        "kind": "organization",
        "aliases": ["PC Doctor", "PC-Doctor"],
        "status": "active",
        "linkedin_publish_as": "organization",
        "linkedin_author_urn": "",
        "notes": "Añadir urn:li:organization:XXX cuando esté la página empresa",
    },
    {
        "entity_id": "ent_innerchispa",
        "slug": "innerchispa",
        "name": "InnerChispa",
        "kind": "organization",
        "aliases": ["Inner Chispa"],
        "status": "active",
    },
    {
        "entity_id": "ent_innerspark",
        "slug": "innerspark",
        "name": "InnerSpark",
        "kind": "organization",
        "aliases": ["Inner Spark"],
        "status": "active",
    },
    {
        "entity_id": "ent_domotika",
        "slug": "domotika",
        "name": "Domotika",
        "kind": "organization",
        "aliases": [],
        "status": "active",
    },
    {
        "entity_id": "ent_iskcon",
        "slug": "iskcon",
        "name": "Iskcon",
        "kind": "organization",
        "aliases": [],
        "status": "active",
    },
    {
        "entity_id": "ent_rafael_personal",
        "slug": "rafael-personal",
        "name": "Rafael López (personal)",
        "kind": "personal",
        "aliases": ["Rafael personal"],
        "status": "active",
        "linkedin_publish_as": "person",
        "linkedin_author_urn": LINKEDIN_AUTHOR_URN or "",
    },
    {
        "entity_id": "ent_creatoros",
        "slug": "creatoros",
        "name": "CreatorOS",
        "kind": "platform",
        "aliases": ["Creator OS"],
        "status": "active",
    },
    {
        "entity_id": "ent_ralfia",
        "slug": "ralphia",
        "name": "Ralphi IA",
        "kind": "platform",
        "aliases": ["RalfAI", "RalfiIA", "RalfIA", "RalfIA MCP", "second brain"],
        "status": "active",
        "notes": "Marca madre — extensión cerebral de Rafael; conector MCP conserva nombre técnico RalfIA.",
    },
]


def main() -> int:
    db = mongo_store.get_db()
    now = datetime.now(timezone.utc).isoformat()
    created = 0
    updated = 0
    for ent in DEFAULT_ENTITIES:
        doc = {**ent, "updated_at": now}
        res = db.entities.update_one(
            {"entity_id": ent["entity_id"]},
            {"$set": doc, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        if res.upserted_id:
            created += 1
        elif res.modified_count:
            updated += 1

    summary = f"entities seed: {created} nuevas, {updated} actualizadas, total {len(DEFAULT_ENTITIES)}"
    print(summary)
    agent_auto_log.record_agent_run(
        "CURSOR",
        action="seed_entities",
        summary=summary,
        project="inneros-db01",
        tool_used="scripts/seed_entities.py",
        metadata={"created": created, "updated": updated},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
