#!/usr/bin/env python3
"""Run the resource auditor without invoking agents or models."""
from pathlib import Path
import sys
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inneros_core_runtime.execution_resource_audit import run

if __name__ == "__main__":
    print(json.dumps(run(notify=True), ensure_ascii=False))
