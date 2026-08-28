"""Create a BSON-aware JSON backup before Daily Life Memory migration."""

from __future__ import annotations

import argparse
from pathlib import Path

from bson import json_util

from raphiia_openai import daily_memory, mongo_store


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    docs = list(mongo_store.get_db()[daily_memory.MEMORIES].find({}))
    args.output.write_text(json_util.dumps(docs, ensure_ascii=False, indent=2), encoding="utf-8")
    print({"ok": True, "collection": daily_memory.MEMORIES, "count": len(docs), "output": str(args.output)})


if __name__ == "__main__":
    main()
