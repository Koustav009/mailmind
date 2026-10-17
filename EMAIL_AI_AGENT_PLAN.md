# Email AI Agent – Complete Build Instruction Plan

> **Purpose of this document**  
> This is a complete, self-contained instruction plan for an AI coding agent (or human developer) to build a production-ready Email AI Agent.  
> Follow the phases strictly. Do not skip architecture decisions.

---

## 1. Project Overview

**Name:** `email-ai-agent`  
**Goal:** An autonomous Python service that runs on an Oracle Cloud VM, continuously monitors an email inbox via IMAP, uses remote LLMs to classify + summarize emails, notifies the user via Telegram, and can safely delete/archive emails only after explicit user confirmation.

### Core Requirements
- Process ~30+ emails/day without missing any (Could Vary)
- Classify importance + category
- Generate concise summaries
- Detect promotions / newsletters / low-value mail
- Ask for confirmation before any destructive action (delete)
- Support **multiple LLM providers simultaneously** (Groq, OpenAI, OpenRouter, Together, Fireworks, Anthropic, custom OpenAI-compatible endpoints)
- Fully open-source stack
- No local LLM inference
- Stateless-friendly but with persistent memory of processed emails
- Designed to run 24/7 on a lightweight Oracle Cloud Free Tier / Always Free VM

### Explicit Non-Goals (for v1)
- Building the Telegram bot from scratch (user already has the bot token)
- Web UI
- Local AI models
- Paid automation platforms (Zapier, Make, n8n cloud, etc.)

---

## 2. High-Level Architecture

```
┌─────────────────┐       ┌──────────────────────┐       ┌─────────────────┐
│  IMAP Poller    │──────▶│  Email Processor     │──────▶│  Action Engine  │
│  (APScheduler)  │       │  (Classifier +       │       │  (Delete /      │
└─────────────────┘       │   Summarizer)        │       │   Archive /     │
                          └──────────┬───────────┘       │   Notify)       │
                                     │                   └────────┬────────┘
                                     ▼                            │
                          ┌──────────────────────┐                │
                          │  Multi-LLM Router    │                │
                          │  (Provider failover  │                │
                          │   + load balancing)  │                │
                          └──────────────────────┘                │
                                     │                            │
                                     ▼                            ▼
                          ┌──────────────────────┐       ┌─────────────────┐
                          │  SQLite / Postgres   │       │  Telegram Bot   │
                          │  (Processed emails,  │       │  (Notifications │
                          │   decisions, rules)  │       │   + Confirmations)
                          └──────────────────────┘       └─────────────────┘
```

---

## 3. Tech Stack (Strict)

| Component              | Technology                                      | Notes |
|------------------------|--------------------------------------------------|-------|
| Language               | Python 3.11+                                     | - |
| Async runtime          | `asyncio` + `aiohttp` / `httpx`                  | Preferred |
| IMAP                   | `aioimaplib` or `imaplib` + `asyncio.to_thread`  | Prefer async |
| Email parsing          | `mail-parser` or standard `email` + `beautifulsoup4` | - |
| LLM clients            | Official SDKs + OpenAI-compatible fallback       | Multi-provider |
| Telegram               | `python-telegram-bot` v21+ (async)               | User already has bot |
| Scheduling             | `APScheduler` (AsyncIOScheduler)                 | - |
| Config                 | `pydantic-settings` + `.env`                     | - |
| Database               | SQLite (default) or Postgres                     | SQLAlchemy 2.0 async |
| Logging                | `structlog` or standard `logging`                | Structured |
| Validation             | `pydantic` v2                                    | Everywhere |
| Package manager        | `uv` or `poetry` (recommend `uv`)                | - |

**Forbidden:**
- n8n, Node-RED, Zapier, Make
- Local Ollama / llama.cpp in the main service
- Any paid SaaS beyond the LLM providers the user chooses

---

## 4. Multi-LLM Provider Support (Critical Feature)

The system **must** support multiple providers at the same time with the following capabilities:

### 4.1 Supported Providers (v1)
- Groq
- OpenAI
- OpenRouter
- Together AI
- Fireworks AI
- Anthropic (Claude)
- Any custom OpenAI-compatible endpoint (base_url + api_key)

### 4.2 Router Requirements
- Configuration-driven (list of providers with priority, model name, max tokens, temperature)
- Automatic failover: if primary provider fails (rate limit, 5xx, timeout) → try next
- Optional load balancing / weighted random
- Per-task model selection (e.g. cheap model for classification, stronger model for important emails)
- Centralized token usage logging
- Easy to add new providers later

### 4.3 Configuration Example (`.env` + settings)

```env
# Primary + fallback order
LLM_PROVIDERS=groq,openrouter,openai

GROQ_API_KEY=...
GROQ_MODEL=llama-3.3-70b-versatile

OPENROUTER_API_KEY=...
OPENROUTER_MODEL=meta-llama/llama-3.3-70b-instruct

OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o-mini

# Optional
LLM_TIMEOUT=45
LLM_MAX_RETRIES=2
```

---

## 5. Recommended Project Structure

```
email-ai-agent/
├── .env.example
├── .gitignore
├── pyproject.toml / requirements.txt
├── README.md
├── src/
│   └── email_agent/
│       ├── __init__.py
│       ├── main.py                 # Entry point + scheduler
│       ├── config.py               # Pydantic settings
│       ├── models/
│       │   ├── email.py
│       │   ├── classification.py
│       │   └── database.py
│       ├── services/
│       │   ├── imap_service.py
│       │   ├── llm_router.py       # Multi-provider brain
│       │   ├── classifier.py
│       │   ├── summarizer.py
│       │   ├── action_service.py
│       │   └── telegram_service.py
│       ├── prompts/
│       │   ├── classify.txt
│       │   └── summarize.txt
│       ├── db/
│       │   ├── session.py
│       │   └── repositories.py
│       └── utils/
│           ├── email_parser.py
│           └── helpers.py
├── tests/
└── scripts/
    └── init_db.py
```

---

## 6. Data Models (Pydantic + SQLAlchemy)

### 6.1 Classification Result (LLM Output)

```python
class EmailClassification(BaseModel):
    importance: Literal["high", "medium", "low"]
    category: Literal[
        "personal", "work", "promotion", "newsletter",
        "transaction", "spam", "notification", "other"
    ]
    summary: str                    # 2-4 sentences max
    action_recommendation: Literal["notify", "archive", "delete", "review"]
    requires_confirmation: bool
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
```

### 6.2 Database Tables
- `processed_emails` (message_id PK, subject, from, classification JSON, processed_at, action_taken, telegram_message_id)
- `user_decisions` (for learning future rules – optional in v1)
- `provider_usage` (optional analytics)

---

## 7. Implementation Phases

### Phase 1 – Foundation (Do first)
1. Create project structure + dependency management
2. Implement `config.py` with multi-provider settings using `pydantic-settings`
3. Implement robust IMAP connection + email fetching (UNSEEN + since last run)
4. Email parsing (subject, from, date, clean text body, HTML → text)
5. SQLite schema + repository layer
6. Basic logging

**Acceptance criteria:** Can connect to IMAP, fetch new emails, store Message-ID, and print clean text.

### Phase 2 – Multi-LLM Router
1. Abstract base provider class
2. Concrete implementations for Groq, OpenAI, OpenRouter, etc.
3. Router with priority list + automatic failover
4. Structured output enforcement (JSON mode or tool calling where available)
5. Token counting / cost estimation (optional but useful)

**Acceptance criteria:** Calling `router.complete(prompt, response_model=EmailClassification)` works across at least 3 providers with failover.

### Phase 3 – Classification & Summarization
1. High-quality system prompts (store in `/prompts`)
2. Single-shot or two-shot classification + summary
3. Handling of long emails (truncate intelligently or map-reduce later)
4. Caching of classification by Message-ID

**Acceptance criteria:** Accurate classification on real emails (promotions detected correctly, important mails flagged).

### Phase 4 – Telegram Integration + Confirmation Flow
1. Send rich notification (summary + importance + buttons)
2. Inline keyboard: `[Delete] [Archive] [Keep] [Show Full]`
3. Handle callback queries securely (only from authorized chat_id)
4. On confirmation → execute IMAP action (move to Trash / delete / add label)
5. Update database with final decision

**Acceptance criteria:** Full loop works: email arrives → classified → Telegram message → user presses Delete → email is moved to Trash.

### Phase 5 – Scheduler + Production Hardening
1. APScheduler jobs (poll every 5–10 minutes)
2. Graceful shutdown
3. Error recovery + dead letter handling
4. Rate limiting protection
5. Daily digest (optional)
6. Health check endpoint (FastAPI optional)

### Phase 6 – Polish & Observability
- Better prompts
- Sender-based rules (whitelist / blacklist)
- Export of decisions
- Simple metrics

---

## 8. Prompt Engineering Guidelines

Create two main prompts:

### Classification Prompt (System)
- Be strict about promotions and newsletters
- Prefer “low” importance for marketing
- Always return valid JSON matching the schema
- Include confidence score

### Key Rules to Encode
- Emails from known contacts / banks / government → higher importance
- “Unsubscribe”, “view in browser”, heavy HTML marketing → promotion
- Transactional (OTP, receipts, shipping) → medium + notify
- Pure spam → low + recommend delete

---

## 9. Security & Safety Rules (Non-negotiable)

1. **Never auto-delete** without explicit confirmation for anything that is not clearly spam with high confidence.
2. Store only Message-ID + metadata, not full email bodies long-term (optional retention policy).
3. Telegram chat_id must be whitelisted.
4. Use App Passwords or OAuth for email (never real password if possible).
5. All secrets via environment variables.
6. Run under a dedicated non-root user on the Oracle VM.
7. IMAP actions must be idempotent.

---

## 10. Deployment on Oracle Cloud VM

1. Ubuntu 22.04 / 24.04 recommended
2. Create dedicated user `emailagent`
3. Use `systemd` service
4. Optional: `docker` + `docker-compose` (acceptable)
5. Log rotation
6. Simple monitoring (healthcheck + Telegram alert on repeated failures)

---

## 11. Future Features (Do not implement in v1 unless asked)

- Learning from user decisions (fine-tune rules)
- Multiple mailbox support
- Vector memory of past emails
- Calendar / todo extraction
- Web dashboard
- Voice notifications

---

## 12. Definition of Done (v1)

- [ ] Runs 24/7 on Oracle Cloud VM
- [ ] Correctly classifies and summarizes new emails
- [ ] Sends Telegram notifications with action buttons
- [ ] Deletes/archives only after user confirmation
- [ ] Supports at least 3 LLM providers with automatic failover
- [ ] No email is processed twice
- [ ] Clean structured logging
- [ ] All configuration via environment variables
- [ ] README with clear setup instructions

---

## 13. Instructions for the Coding AI

When implementing:

1. Follow the phase order.
2. Prefer async everywhere possible.
3. Use type hints + Pydantic models strictly.
4. Write clean, readable, production-quality code.
5. Add docstrings to public methods.
6. Make the LLM router the most robust part of the system.
7. Never hardcode API keys or credentials.
8. After each phase, the code should be runnable and testable.

**Start with Phase 1.**

---

*End of Instruction Plan*