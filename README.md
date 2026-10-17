# Email AI Agent

An autonomous Python service that monitors an email inbox over IMAP, classifies
and summarizes every message with remote LLMs (Groq, OpenRouter, custom
OpenAI-compatible gateways, and more), notifies you on Telegram with one-tap
action buttons, and moves mail to Trash/Archive **only after your explicit
confirmation**.

- ~30+ emails/day, 24/7, lightweight (Oracle Cloud Free Tier friendly)
- Multi-provider LLM router with automatic failover and usage logging
- Never auto-deletes: every destructive action needs a whitelisted Telegram confirmation
- Stores only metadata + classification (no email bodies in the database)
- Fully open source, no local AI inference, no paid automation platforms

## Architecture

```
IMAP Poller (APScheduler, 5 min)
  └─> Email Processor (dedupe by Message-ID)
        └─> Classifier (single-shot classify + summarize via Multi-LLM Router)
              └─> Telegram notification with [Delete] [Archive] [Keep] [Show Full]
                    └─> Action Engine executes your confirmed choice via IMAP
SQLite (SQLAlchemy 2.0 async) records processed emails, decisions, provider usage
```

## Quick start (uv)

```bash
git clone <this repo> && cd email-ai-agent
uv sync
cp .env.example .env      # fill in IMAP, Telegram and LLM credentials
mkdir -p data
uv run python scripts/init_db.py
uv run python -m email_agent.main
```

## Docker (recommended for the Oracle VM)

```bash
cp .env.example .env      # set DATABASE_URL=sqlite+aiosqlite:////app/data/agent.db
docker compose up -d --build
docker compose logs -f
```

Data persists in the `agent-data` volume; log rotation is configured in
`docker-compose.yml`. The container runs as a non-root user (`emailagent`).

### systemd alternative

```ini
# /etc/systemd/system/email-ai-agent.service
[Unit]
Description=Email AI Agent
After=network-online.target

[Service]
User=emailagent
WorkingDirectory=/opt/email-ai-agent
ExecStart=/opt/email-ai-agent/.venv/bin/python -m email_agent.main
Restart=always
EnvironmentFile=/opt/email-ai-agent/.env

[Install]
WantedBy=multi-user.target
```

## Configuration

All configuration is via environment variables (or `.env`). See
[`.env.example`](.env.example) for the full list. Highlights:

| Variable | Meaning |
|---|---|
| `LLM_PROVIDERS` | Comma-separated provider names in failover priority order, e.g. `groq,openrouter,custom` |
| `CUSTOM_BASE_URL` / `CUSTOM_API_KEY` | Any OpenAI-compatible gateway (LiteLLM, vLLM, Gemini-compat, ...) |
| `*_MODEL` / `*_MODEL_STRONG` | Default (cheap) model per provider; `_STRONG` is used for strong tasks if set |
| `LLM_STRATEGY` | `priority` (failover order) or `weighted` (randomized load spread) |
| `TELEGRAM_CHAT_IDS` | Whitelisted chat ids (comma-separated). The first id receives notifications; buttons from any other chat are rejected |
| `POLL_INTERVAL_MINUTES` | IMAP polling interval (default 5) |
| `IMAP_LOOKBACK_DAYS` | Only fetch unread mail from the last N days (default 2) — protects against huge unread backlogs |
| `SENDER_WHITELIST` / `SENDER_BLACKLIST` | Comma-separated emails or `@domain` suffixes that override classification |
| `FAILURES_BEFORE_ALERT` | Consecutive failed poll cycles before a Telegram alert (default 3) |

### Telegram setup

1. Create a bot with [@BotFather](https://t.me/BotFather), put the token in `TELEGRAM_BOT_TOKEN`.
2. Message your bot once, then get your chat id (e.g. via `https://api.telegram.org/bot<TOKEN>/getUpdates`)
   and put it in `TELEGRAM_CHAT_IDS`.
3. Pressing **Delete** or **Archive** on a notification is the explicit confirmation;
   the button is disabled after the first press (idempotent re-presses do nothing).

### Email account

Use an App Password (Gmail, Outlook, ...) or an app-specific credential — never
your primary password. The agent fetches `UNSEEN` messages with `BODY.PEEK`,
marks them read **only after** they are safely recorded, and dedupes on
`Message-ID`, so no mail is ever processed twice or lost.

## Behavior details

- **Classification**: importance (high/medium/low), category (personal, work,
  promotion, newsletter, transaction, spam, notification, other), 2-4 sentence
  summary, action recommendation, reason, confidence — validated strictly
  against a Pydantic schema.
- **Show Full** re-fetches the message from IMAP and streams the cleaned body to
  Telegram in chunks (bodies are never stored in the database).
- **LLM outage**: the email is recorded as a dead letter (`action_taken=error`)
  and you get a "review manually" notice; the queue keeps moving.
- **Token usage** for every LLM call lands in `provider_usage` for cost tracking.

## Development

```bash
uv run pytest          # unit tests (IMAP/Telegram/LLM are mocked)
```

Useful scripts:

| Script | Purpose |
|---|---|
| `scripts/init_db.py` | Create the database schema |
| `scripts/check_phase1.py` | Live IMAP smoke test (fetch + parse + store) |
| `scripts/check_phase2.py` | Live LLM router smoke test (classification JSON) |
| `scripts/export_decisions.py` | Export your confirmations to CSV/JSON |

## Security

- Secrets only via environment variables — never committed (`.env` is gitignored).
- Telegram callbacks are accepted **only** from whitelisted chat ids.
- No destructive IMAP action without explicit confirmation.
- Only Message-ID + metadata + classification are persisted; bodies are discarded.
- IMAP actions are idempotent; the DB write always precedes marking mail read.
- Run under a dedicated non-root user (the Docker image does this by default).
