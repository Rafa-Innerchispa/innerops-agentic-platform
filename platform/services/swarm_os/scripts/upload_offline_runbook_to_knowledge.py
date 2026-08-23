#!/usr/bin/env python3
"""Sube el runbook offline a Knowledge de Open WebUI (ejecutar dentro del contenedor)."""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, "/app/backend")

RUNBOOK = Path("/app/backend/data/offline-knowledge/RALFIA_OFFLINE_RUNBOOK.md")
KB_NAME = "RalfIA Offline"
KB_DESC = "Runbook LAN sin internet: puertos, proyectos, procedimientos"
MODEL_ID = "ralfia-offline"
RUNBOOK_NAME = "RALFIA_OFFLINE_RUNBOOK.md"


async def main() -> None:
    from sqlalchemy import select
    from open_webui.internal.db import get_async_db_context
    from open_webui.models.files import FileForm, Files
    from open_webui.models.knowledge import KnowledgeForm, Knowledges
    from open_webui.models.models import ModelForm, Models
    from open_webui.models.users import User
    from open_webui.routers.retrieval import ProcessFileForm, process_file

    if not RUNBOOK.is_file():
        raise SystemExit(f"Missing runbook: {RUNBOOK}")

    content = RUNBOOK.read_text(encoding="utf-8")

    from open_webui.main import app

    class _Req:
        pass

    _Req.app = app

    async with get_async_db_context() as db:
        admin = (await db.execute(select(User).where(User.role == "admin").limit(1))).scalars().first()
        if not admin:
            raise SystemExit("No admin user")

        existing = await Knowledges.search_knowledge_bases(admin.id, filter={"query": KB_NAME}, limit=10, db=db)
        kb = next((item for item in existing.items if item.name == KB_NAME), None)
        if not kb:
            kb = await Knowledges.insert_new_knowledge(
                admin.id,
                KnowledgeForm(name=KB_NAME, description=KB_DESC, access_grants=[]),
                db=db,
            )
        if not kb:
            raise SystemExit("Could not create knowledge base")
        print(f"KB {kb.id} {kb.name}")

        files_resp = await Knowledges.get_files_by_id(kb.id, db=db)
        for linked in files_resp or []:
            name = (linked.meta or {}).get("name") or linked.filename
            if name == RUNBOOK_NAME:
                print(f"Already attached: {name}")
                kb_id = kb.id
                break
        else:
            file_id = str(uuid.uuid4())
            file_form = FileForm(
                id=file_id,
                filename=RUNBOOK_NAME,
                path="",
                data={"content": content},
                meta={
                    "name": RUNBOOK_NAME,
                    "content_type": "text/markdown",
                    "size": len(content),
                },
            )
            file = await Files.insert_new_file(admin.id, file_form, db=db)
            if not file:
                raise SystemExit("File insert failed")
            print(f"File {file.id} ({len(content)} chars)")

            await process_file(
                _Req(),
                ProcessFileForm(file_id=file.id, collection_name=kb.id),
                user=admin,
                db=db,
            )
            await Knowledges.add_file_to_knowledge_by_id(
                knowledge_id=kb.id,
                file_id=file.id,
                user_id=admin.id,
                directory_id=None,
                db=db,
            )
            print("Indexed and attached")
            kb_id = kb.id

        model = await Models.get_model_by_id(MODEL_ID, db=db)
        if model:
            meta = dict(model.meta or {})
            meta["knowledge"] = [{"id": kb_id, "name": KB_NAME}]
            meta.setdefault("capabilities", {})
            meta["capabilities"]["memory"] = True
            await Models.update_model_by_id(
                MODEL_ID,
                ModelForm(
                    id=model.id,
                    base_model_id=model.base_model_id,
                    name=model.name,
                    meta=meta,
                    params=model.params,
                    is_active=model.is_active,
                ),
                db=db,
            )
            print(f"Model {MODEL_ID} linked to KB")
        else:
            print(f"WARN model {MODEL_ID} not found")

    print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
