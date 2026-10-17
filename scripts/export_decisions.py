"""Export user decisions (confirmations) from the database to CSV or JSON."""

import argparse
import asyncio
import csv
import io
import json

from email_agent.config import Settings
from email_agent.db.repositories import DecisionRepository
from email_agent.db.session import make_engine, make_session_factory
from email_agent.utils.helpers import ensure_utf8_stdout


async def collect_rows(settings: Settings) -> list[dict]:
    engine = make_engine(settings.database_url)
    try:
        decisions = await DecisionRepository(make_session_factory(engine)).list_all()
    finally:
        await engine.dispose()
    return [
        {
            "id": d.id,
            "message_id": d.message_id,
            "decision": d.decision,
            "decided_at": d.decided_at.isoformat(),
        }
        for d in decisions
    ]


def render(rows: list[dict], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(rows, indent=2)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=["id", "message_id", "decision", "decided_at"])
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


async def main() -> None:
    ensure_utf8_stdout()
    parser = argparse.ArgumentParser(description="Export user decisions to CSV or JSON")
    parser.add_argument("--format", choices=["csv", "json"], default="csv")
    parser.add_argument("--output", help="Output file path (prints to stdout if omitted)")
    args = parser.parse_args()

    rows = await collect_rows(Settings())
    text = render(rows, args.format)
    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        print(f"Wrote {len(rows)} decision(s) to {args.output}")
    else:
        print(text)


if __name__ == "__main__":
    asyncio.run(main())
