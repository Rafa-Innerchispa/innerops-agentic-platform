#!/usr/bin/env python3
"""Dry-run/apply canonical owner identities without printing phone numbers."""

from __future__ import annotations

import argparse
import json

from raphiia_openai import whatsapp_identity


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner-primary", help="Única línea humana con capacidad de confirmar")
    parser.add_argument("--operational-line", action="append", default=[], help="Línea que solo consulta y solicita")
    parser.add_argument("--owner-line", action="append", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--no-evolution", action="store_true")
    args = parser.parse_args()
    configured = args.owner_line or whatsapp_identity.configured_owner_lines_from_env()
    primary = args.owner_primary or (configured[0] if configured else "")
    operational = list(args.operational_line) or configured[1:]
    lines = [primary, *operational]
    result = whatsapp_identity.bootstrap_owner_registry(
        lines,
        include_evolution=not args.no_evolution,
        apply=args.apply,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
