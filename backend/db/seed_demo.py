"""Command line: ``python -m db.seed_demo [--reset]`` (run from the backend directory).

Requires DATABASE_URL and DMERS_ALLOW_DEMO_SEED=1. The same operation is available as
``flask --app run seed-demo [--reset]``.
"""
from __future__ import annotations

import argparse
import json
import sys

from .migrate import apply_pending
from .pool import database_url
from .seed import seed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Load the Review II demonstration data into the response schema")
    parser.add_argument("--reset", action="store_true", help="remove existing response-model rows first")
    args = parser.parse_args(argv)
    try:
        apply_pending(database_url())
        print(json.dumps(seed(reset=args.reset), indent=2))
    except (PermissionError, RuntimeError) as error:
        print(f"seed-demo: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
