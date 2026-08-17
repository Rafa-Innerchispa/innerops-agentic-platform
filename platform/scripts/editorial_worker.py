#!/usr/bin/env python3
"""Worker editorial — imágenes, vídeos y publicación automática."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from raphiia_openai import editorial_store, image_gen, linkedin_client  # noqa: E402
from raphiia_openai.editorial_publish import publish_destination  # noqa: E402

INTERVAL = int(os.environ.get("EDITORIAL_WORKER_INTERVAL", "90"))


def process_images() -> int:
    if os.environ.get("EDITORIAL_AUTO_IMAGE", "0") != "1":
        return 0
    n = 0
    for draft in editorial_store.drafts_needing_image(limit=3):
        did = draft["_id"]
        editorial_store.update_draft(did, {"status": editorial_store.STATUS_GENERATING})
        gen = image_gen.generate_for_draft(
            did,
            draft.get("title", ""),
            draft.get("markdown", draft.get("body", "")),
        )
        if gen.get("ok"):
            editorial_store.attach_media(
                did,
                media_path=gen["media_path"],
                media_prompt=gen["media_prompt"],
                provider=gen["provider"],
            )
            n += 1
            print(f"image OK {did} via {gen['provider']}")
    return n


def process_videos() -> int:
    if os.environ.get("EDITORIAL_AUTO_VIDEO", "0") != "1":
        return 0
    from raphiia_openai.video_pipeline.pipeline import generate_video

    n = 0
    for draft in editorial_store.drafts_needing_video(limit=2):
        did = draft["_id"]
        title = draft.get("title") or "InnerChispa"
        script = draft.get("markdown") or draft.get("body") or ""
        entity_id = draft.get("entity_id") or "ent_innerchispa"
        aspect = draft.get("video_aspect") or "9:16"
        editorial_store.update_draft(did, {"status": editorial_store.STATUS_GENERATING})
        result = generate_video(
            title=title,
            script=script,
            entity_id=entity_id,
            aspect=aspect,
            draft_id=did,
            auto_publish=os.environ.get("EDITORIAL_AUTO_VIDEO_PUBLISH", "0") == "1",
            destinations=["whatsapp_status", "web"],
        )
        if result.get("ok"):
            n += 1
            print(f"video OK {did} -> {result.get('video_path')}")
        else:
            editorial_store.update_draft(did, {"status": editorial_store.STATUS_REVIEW})
            print(f"video FAIL {did}: {result.get('error')}")
    return n


def process_publish_queue() -> int:
    if os.environ.get("EDITORIAL_AUTO_PUBLISH", "0") != "1":
        return 0
    if not linkedin_client.config_status().get("ready"):
        return 0
    n = 0
    for dest in editorial_store.list_queued_destinations(limit=5):
        rid = dest["_id"]
        result = publish_destination(rid)
        if result.get("ok"):
            n += 1
            print(f"published {rid} -> {result.get('linkedin_urn')}")
        else:
            print(f"publish skip/fail {rid}: {result.get('error')}")
    return n


def tick() -> None:
    ni = process_images()
    nv = process_videos()
    np = process_publish_queue()
    print(f"tick images={ni} videos={nv} publishes={np}")


def main() -> None:
    auto_img = os.environ.get("EDITORIAL_AUTO_IMAGE", "0")
    auto_vid = os.environ.get("EDITORIAL_AUTO_VIDEO", "0")
    auto_pub = os.environ.get("EDITORIAL_AUTO_PUBLISH", "0")
    print(
        f"Editorial worker interval={INTERVAL}s "
        f"auto_image={auto_img} auto_video={auto_vid} auto_publish={auto_pub}"
    )
    while True:
        try:
            tick()
        except Exception as exc:
            print(f"error: {exc}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
