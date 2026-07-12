"""Fleet CLI: run the story ticks against a live gateway.

Usage: python -m fleet.run [--ticks N] [--reset]

--reset clears working memory, actions, transcripts, and the delivery ledger;
it NEVER touches custody rows. A non-clean custody store fails fast instead
(deterministic demos never upsert).
"""

from __future__ import annotations

import argparse

from fleet import story
from fleet.agents import run_ticks, setup
from fleet.bootstrap import ensure_agent_memory, reset_runtime
from fleet.gateway import GatewayClient
from services.common.logging import configure

log = configure("fleet")


def main() -> None:
    parser = argparse.ArgumentParser(description="Recant fleet: scripted story agents")
    parser.add_argument("--ticks", type=int, default=story.MAX_TICK)
    parser.add_argument("--reset", action="store_true", help="clear runtime state first (never custody)")
    args = parser.parse_args()

    story.check_story()
    ensure_agent_memory()
    if args.reset:
        reset_runtime()
        log.info("runtime state reset (custody untouched)")

    fleet = setup(GatewayClient())
    run_ticks(fleet, args.ticks)

    print(f"fleet ran {args.ticks} tick(s): {len(fleet.belief_ids)} beliefs, {len(fleet.action_ids)} pending action(s)")
    if "forum_claim" in fleet.belief_ids:
        print(f"recant target: sources[forum_thread] = {fleet.source_ids['forum_thread']}")


if __name__ == "__main__":
    main()
