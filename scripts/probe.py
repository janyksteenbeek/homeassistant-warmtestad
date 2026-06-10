#!/usr/bin/env python3
"""Standalone probe for the Warmtestad Blazor portal client.

Run this with your own credentials to validate / iterate on the reverse-engineered
protocol *outside* Home Assistant. (Claude can't run this itself because it must
not handle your password.) The whole flow can also be exercised with a *wrong*
password: the portal renders an inline "incorrect" message over the circuit,
which proves the login mechanics work without revealing anything.

Usage:

    pip install aiohttp msgpack
    WARMTESTAD_EMAIL='you@example.com' WARMTESTAD_PASSWORD='secret' \
        python scripts/probe.py -v
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Import the client module directly (without triggering the HA package __init__).
sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent / "custom_components" / "warmtestad")
)

from blazor_client import (  # noqa: E402
    WarmtestadAuthError,
    WarmtestadBlazorClient,
    WarmtestadError,
)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    email = os.environ.get("WARMTESTAD_EMAIL")
    password = os.environ.get("WARMTESTAD_PASSWORD")
    if not email or not password:
        print(
            "Set WARMTESTAD_EMAIL and WARMTESTAD_PASSWORD environment variables.",
            file=sys.stderr,
        )
        return 2

    async with WarmtestadBlazorClient(email, password) as client:
        try:
            print(">>> Logging in ...")
            await client.login()
            print("    Login OK")
            print(">>> Reading consumption ...")
            value = await client.async_get_consumption_gj()
            print(f">>> Consumption (Verbruik): {value} GJ")
        except WarmtestadAuthError as err:
            print(f"!!! Auth error: {err}", file=sys.stderr)
            return 1
        except WarmtestadError as err:
            print(f"!!! Error: {err}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
