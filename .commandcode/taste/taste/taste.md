# Taste
- Wants to be asked about every decision before it is made — present options and let the user choose rather than deciding unilaterally (explicitly stated: "Ask me about every desition"). Confidence: 0.95
- Plan-first workflow: fully understand the project requirements and produce a proper written plan before any implementation starts. Confidence: 0.9
- Keeps the plan open for revision until fully satisfied — declined to exit plan mode even after all decisions were locked and the plan was written, preferring to keep refining first. Confidence: 0.8
- Before committing to infrastructure/tooling choices, wants the tradeoffs spelled out first (e.g. asked for a SQLite-vs-Supabase-Postgres difference breakdown before making the call). Confidence: 0.8
- Prefers self-contained, robust defaults over external managed services for small self-hosted deployments: after reviewing the tradeoffs, kept SQLite over a free Supabase Postgres (local write reliability + metadata privacy). Confidence: 0.7
- Has a free-tier Supabase Postgres instance available for projects. Confidence: 0.75
