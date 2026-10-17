"""Initialize the database schema defined in email_agent.models.database."""

import asyncio

from email_agent.config import Settings
from email_agent.db.session import init_db, make_engine


async def main() -> None:
    settings = Settings()
    engine = make_engine(settings.database_url)
    await init_db(engine)
    await engine.dispose()
    print(f"Database initialized: {settings.database_url}")


if __name__ == "__main__":
    asyncio.run(main())
