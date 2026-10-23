"""Lightweight pre-publish self-check. Not a substitute for a full security review."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "__pycache__", "build", "dist", ".pytest_cache"}
NEVER_SHIP = {".env", "id_rsa", "id_ed25519"}
RULES = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github_token": re.compile(r"\b(?:ghp|gho|ghs|ghu|ghr)_[A-Za-z0-9]{25,}"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "switch_live_token": re.compile(r"\bsk_switch_live_[A-Za-z0-9]{16,}"),
}


def main():
    alerts = []
    inspected = 0
    for p in ROOT.rglob("*"):
        if p.is_dir() or any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts):
            continue
        if p.name in NEVER_SHIP:
            alerts.append(f"forbidden filename: {p.relative_to(ROOT)}")
        if p.suffix in {".zip", ".pyc", ".png", ".jpg", ".pdf"}:
            continue
        try:
            content = p.read_text(encoding="utf-8")
        except (UnicodeError, OSError):
            continue
        inspected += 1
        for name, pattern in RULES.items():
            if pattern.search(content):
                alerts.append(f"{p.relative_to(ROOT)} matches {name}")
    if alerts:
        print("PRE-PUBLISH FAIL: " + "; ".join(alerts))
        return 1
    print(f"PRE-PUBLISH PASS: {inspected} text files checked (not a full audit)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
