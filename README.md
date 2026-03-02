# Slack Intelligence Hub

Automated Slack triage, TODO management, and activity digests for busy product managers.

`slack-hub` continuously monitors your Slack channels, classifies threads by relevance and urgency using LLMs, maintains an auto-updated TODO list in Google Sheets, and delivers scheduled email digests.

## What It Does

- **On-Demand Digest** — CLI-generated snapshot of channel activity, prioritized by relevance
- **Auto-Maintained TODO List** — Google Sheet of action items extracted from Slack, with manual override and feedback loop
- **Daily Brief** (7 AM) — Full TODO list, overnight summary, activity stats
- **Hourly Pulse** (11 AM–5 PM) — Lightweight email with new TODOs, mentions, and channel activity

## Quick Start

```bash
# 1. Clone
git clone https://github.com/cdalmeida/Slackhub
cd Slackhub

# 2. Install (creates venv, installs deps, initializes DB)
make install

# 3. Activate the virtual environment
source .venv/bin/activate

# 4. Interactive setup
slack-hub init

# 5. Pick your channels
slack-hub channels setup

# 6. Run your first digest
slack-hub digest
```

## Prerequisites

- **Python 3.11+**
- **Slack CLI** installed and authenticated (`slack auth token`)
- **At least one LLM provider API key** (you can mix and match per task):
  - **Google AI** — Gemini 2.0 Flash (fast + cheap for classification)
  - **OpenAI** — GPT-4o / GPT-4o-mini (good all-around, Azure OpenAI supported via `openai_base_url`)
  - **Anthropic** — Claude Sonnet / Haiku (best summarization quality)
  - **Ollama** — Local models (air-gapped, free, lower quality)
- **Google Service Account** with Sheets API access (optional — falls back to local display)

## Commands

| Command | Description |
|---------|-------------|
| `slack-hub init` | Interactive setup wizard |
| `slack-hub channels setup` | Pick channels from Slack |
| `slack-hub channels list` | Show configured channels |
| `slack-hub fetch` | Fetch messages from Slack |
| `slack-hub classify` | Run LLM classification |
| `slack-hub digest` | Full pipeline: fetch → classify → digest |
| `slack-hub digest --hours 24` | Custom lookback window |
| `slack-hub todos list` | Show open TODOs |
| `slack-hub todos done <id>` | Mark TODO as complete |
| `slack-hub todos dismiss <id>` | Dismiss a TODO |
| `slack-hub todos refresh` | Check for auto-resolved TODOs |
| `slack-hub email-digest --type daily` | Send daily brief |
| `slack-hub email-digest --type hourly` | Send hourly pulse |
| `slack-hub watch` | Background polling mode |
| `slack-hub stats` | Activity statistics |

## Scheduling Emails

Add to your crontab (`crontab -e`):

```bash
# Daily brief — 7 AM PT weekdays
0 7 * * 1-5 /path/to/slack-hub/.venv/bin/slack-hub email-digest --type daily

# Hourly pulse — 11 AM through 5 PM PT weekdays
0 11-17 * * 1-5 /path/to/slack-hub/.venv/bin/slack-hub email-digest --type hourly
```

## Configuration

All settings live in `config/config.yaml`. Key sections:

- **channels** — organized by priority tier (high/medium/low)
- **direct_messages** — opt-in DM monitoring with allowlist
- **llm** — per-task model selection across 4 providers (Google Gemini, OpenAI GPT, Anthropic Claude, Ollama local)
- **email** — daily and hourly digest settings with smart suppression
- **todo** — Google Sheets ID and auto-complete settings

See `config/config.example.yaml` for the full template.

## Architecture

```
Slack API → Ingestion → SQLite → Classification (LLM) → Google Sheets
                                                       → Digest → Email
```

Everything runs locally. No shared servers. Each user's instance only sees their own channels.

## LLM Cost

Each task is independently configurable. Example configurations at typical PM volumes (~300–500 msgs/day):

**Gemini + OpenAI (recommended if no Anthropic access):**

| Task | Model | ~Cost/Day |
|------|-------|-----------|
| Classification | Gemini 2.0 Flash | $0.02–$0.05 |
| TODO Extraction | GPT-4o-mini | $0.02–$0.06 |
| Summarization | GPT-4o | $0.10–$0.25 |
| Resolution Detection | Gemini 2.0 Flash | $0.01–$0.03 |
| **Total** | | **$0.15–$0.39** |

**Gemini + Anthropic:**

| Task | Model | ~Cost/Day |
|------|-------|-----------|
| Classification | Gemini 2.0 Flash | $0.02–$0.05 |
| TODO Extraction | Claude Haiku 4.5 | $0.03–$0.08 |
| Summarization | Claude Sonnet 4.5 | $0.10–$0.30 |
| Resolution Detection | Gemini 2.0 Flash | $0.01–$0.03 |
| **Total** | | **$0.16–$0.46** |

**All-OpenAI:**

| Task | Model | ~Cost/Day |
|------|-------|-----------|
| Classification | GPT-4o-mini | $0.02–$0.06 |
| TODO Extraction | GPT-4o-mini | $0.02–$0.06 |
| Summarization | GPT-4o | $0.10–$0.25 |
| Resolution Detection | GPT-4o-mini | $0.01–$0.03 |
| **Total** | | **$0.15–$0.40** |

## Security

- Slack tokens are user-scoped and stored locally
- LLM calls can be routed through an internal gateway (via `openai_base_url` for Azure/proxy setups), commercial APIs, or run locally via Ollama
- Google Sheets credentials are scoped to a single spreadsheet
- All credential files are excluded from version control

## License

MIT
