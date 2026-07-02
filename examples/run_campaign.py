"""Forum's conscious campaign layer: declare, run best-effort, ingest external status.

Loads the ~10-repo flagship campaign, runs the forum-owned features best-effort to
a fixed point with an offline echo executor, ingests an external status for telos,
and prints the reduced, witnessed campaign room. Runs offline, nothing to install.

Run:  python examples/run_campaign.py
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from forum.campaign import campaign_from_payload, declare_campaign
from forum.campaign_dispatch import run_campaign
from forum.campaign_ingest import ingest_feature_status
from forum.campaign_room import build_campaign_room, campaign_room_text
from forum.executor import EchoExecutor
from forum.ledger import InMemoryStorage, Ledger


def main() -> None:
    body = json.loads((pathlib.Path(__file__).parent / "flagship_campaign.json").read_text())
    campaign = campaign_from_payload(body)

    ticks = iter(float(t) for t in range(1, 1_000_000))
    ledger = Ledger(InMemoryStorage(), clock=lambda: next(ticks))

    declare_campaign(ledger, campaign)

    # Best-effort dispatch of every runnable forum-owned feature to a fixed point.
    asyncio.run(run_campaign(ledger, campaign, EchoExecutor()))

    # An external owner (telos) reports its own status; forum records, never runs it.
    ingest_feature_status(
        ledger, campaign.campaign_id, "telos", "telos-engine-showcase", "done",
        source="external:telos", reason="showcase shipped",
    )

    room = build_campaign_room(ledger, campaign.campaign_id)
    print(campaign_room_text(room))
    print()
    print("ledger entries   :", len(ledger.replay()))
    print("verify(deep=True):", ledger.verify(deep=True))


if __name__ == "__main__":
    main()
