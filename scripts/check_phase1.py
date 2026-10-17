"""Phase 1 checkpoint: connect to IMAP, fetch new emails, store Message-IDs, print clean text.

Requires a filled-in .env (IMAP_* and Telegram vars; LLM keys are not used here
but Settings validation requires the configured providers to have keys).
"""

import asyncio
from datetime import date, timedelta

from email_agent.config import Settings
from email_agent.db.repositories import EmailRepository
from email_agent.db.session import init_db, make_engine, make_session_factory
from email_agent.log import configure_logging
from email_agent.services.imap_service import ImapService
from email_agent.utils.email_parser import parse_email
from email_agent.utils.helpers import ensure_utf8_stdout, format_imap_date


async def main() -> None:
    ensure_utf8_stdout()
    settings = Settings()
    configure_logging(settings.log_level)

    engine = make_engine(settings.database_url)
    await init_db(engine)
    repo = EmailRepository(make_session_factory(engine))

    imap = ImapService(
        host=settings.imap_host,
        port=settings.imap_port,
        user=settings.imap_user,
        password=settings.imap_password,
        folder=settings.imap_folder,
        archive_folder=settings.imap_archive_folder,
        trash_folder=settings.imap_trash_folder,
    )
    await imap.connect()
    since = format_imap_date(date.today() - timedelta(days=settings.imap_lookback_days))
    fetched = await imap.fetch_unseen(since=since)
    print(f"Fetched {len(fetched)} unseen message(s) since {since}\n", flush=True)

    for uid, _flags, raw in fetched:
        email = parse_email(raw, uid=uid)
        await repo.add(
            message_id=email.message_id,
            uid=email.uid,
            subject=email.subject,
            from_addr=email.from_addr,
            mail_date=email.date,
            classification=None,
        )
        print(f"--- uid={uid} message_id={email.message_id}", flush=True)
        print(f"From:    {email.from_name} <{email.from_addr}>", flush=True)
        print(f"Subject: {email.subject}", flush=True)
        print(f"Date:    {email.date}", flush=True)
        print(email.body_text[:500], flush=True)
        print(flush=True)

    await imap.disconnect()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
