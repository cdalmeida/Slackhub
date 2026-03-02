# Slack Intelligence Hub

Automated Slack triage, TODO management, and activity digests for busy product managers.

`slack-hub` continuously monitors your Slack channels, classifies threads by relevance and urgency using LLMs, maintains an auto-updated TODO list in Google Sheets, and delivers scheduled email digests.

## What It Does

- **On-Demand Digest** -- CLI-generated snapshot of channel activity, prioritized by relevance
- **Auto-Maintained TODO List** -- Google Sheet of action items extracted from Slack, with manual override and feedback loop
- **Daily Brief** (7 AM) -- Full TODO list, overnight summary, activity stats
- **Hourly Pulse** (11 AM--5 PM) -- Lightweight email with new TODOs, mentions, and channel activity

## Prerequisites

- **Python 3.11+** (3.12 recommended)
  - macOS: `brew install python@3.12`
  - Verify: `python3.12 --version`
- **Slack CLI** installed and authenticated:
  ```bash
  curl -fsSL https://downloads.slack-edge.com/slack-cli/install.sh | bash
  slack login
  ```
- **At least one LLM provider API key** (you can mix and match per task):
  - **Google AI** -- Gemini 2.0 Flash (fast + cheap for classification)
  - **OpenAI** -- GPT-4o / GPT-4o-mini (good all-around, Azure OpenAI supported via `openai_base_url`)
  - **Anthropic** -- Claude Sonnet / Haiku (best summarization quality)
  - **Ollama** -- Local models (air-gapped, free, lower quality)
- **Google Sheets** (optional -- falls back to local TODO display). Two connection methods:
  - **Apps Script webhook** -- no service account or admin permissions needed
  - **Service account** -- requires a Google Cloud project with Sheets API enabled

## Quick Start

```bash
# 1. Clone
git clone https://github.com/cdalmeida/Slackhub.git
cd Slackhub/slackhubv1

# 2. Install (creates venv with Python 3.12, installs deps, initializes DB)
make install

# 3. Activate the virtual environment
source .venv/bin/activate

# 4. Interactive setup (Slack token, LLM keys, Google Sheets)
slack-hub init

# 5. Pick your channels
slack-hub channels setup

# 6. Run your first digest
slack-hub digest
```

## Google Sheets Setup

The init wizard offers three options for the TODO list:

### Option 1: Apps Script Webhook (recommended)

No service account or Google Cloud project required. Works with any Google Workspace account.

1. Create a new Google Sheet at https://sheets.google.com
2. Go to **Extensions > Apps Script**
3. Delete the default code and paste the contents of `slack_hub/apps_script.js`
4. Click **Deploy > New Deployment**
5. Set type to **Web app**, execute as **Me**, access **Anyone**
6. Click **Deploy** and copy the deployment URL
7. Run `slack-hub init` and choose option `[1]`, then paste the URL

### Option 2: Service Account

Requires a Google Cloud project with Sheets API and Drive API enabled.

1. Create a service account in Google Cloud Console
2. Download the JSON key file to `~/.slack-hub/google-creds.json`
3. Create a Google Sheet and share it (Editor) with the service account email
4. Copy the Sheet ID from the URL (the long string between `/d/` and `/edit`)
5. Run `slack-hub init` and choose option `[2]`, then paste the Sheet ID

### Option 3: Local Only

Skip Google Sheets entirely. TODOs are stored in the local SQLite database and displayed via `slack-hub todos list`.

## Enterprise Grid / Restricted Workspaces

Some Slack Enterprise Grid workspaces restrict channel listing APIs (`conversations.list` and `users.conversations`). If you see an `enterprise_is_restricted` error during `slack-hub channels setup`, the tool automatically switches to **manual entry mode**.

In manual mode, you enter each channel as `#channel-name CHANNEL_ID`. To find a channel's ID:

1. Right-click the channel name in Slack → **View channel details**
2. Scroll to the bottom — the **Channel ID** is displayed (e.g. `C01AB2CDE`)

Or: right-click → **Copy link** — the ID is the last path segment of the URL.

## Commands

| Command | Description |
|---------|-------------|
| `slack-hub init` | Interactive setup wizard |
| `slack-hub channels setup` | Pick channels from Slack |
| `slack-hub channels list` | Show configured channels |
| `slack-hub fetch` | Fetch messages from Slack |
| `slack-hub classify` | Run LLM classification |
| `slack-hub digest` | Full pipeline: fetch -> classify -> digest |
| `slack-hub digest --hours 24` | Custom lookback window |
| `slack-hub todos list` | Show open TODOs |
| `slack-hub todos done <id>` | Mark TODO as complete |
| `slack-hub todos dismiss <id>` | Dismiss a TODO |
| `slack-hub todos refresh` | Check for auto-resolved TODOs |
| `slack-hub email-digest --type daily` | Send daily brief |
| `slack-hub email-digest --type hourly` | Send hourly pulse |
| `slack-hub watch` | Background polling mode |
| `slack-hub stats` | Activity statistics |

## Project Structure

```
slackhubv1/
  pyproject.toml          # Package config and dependencies
  Makefile                # Install, run, lint, clean targets
  config/
    config.example.yaml   # Template for all settings
    config.yaml           # Your config (created on first install)
  slack_hub/              # Python package
    __init__.py           # Data classes (Classification, TodoExtraction, etc.)
    cli.py                # Click CLI entrypoint
    config.py             # YAML config loader
    db.py                 # SQLite database layer
    ingestion.py          # Slack message fetching and normalization
    classifier.py         # LLM orchestration for classification
    digest.py             # Markdown digest generator
    sheets.py             # Google Sheets sync (webhook, service account, or local)
    email_digest.py       # Email delivery (Gmail API or SMTP)
    apps_script.js        # Google Apps Script to deploy in your Sheet
    openai_provider.py    # GPT-4o / GPT-4o-mini provider
    anthropic_provider.py # Claude Sonnet / Haiku provider
    google_provider.py    # Gemini Flash provider
    ollama_provider.py    # Local Ollama provider
    templates/
      daily_brief.html.j2
      hourly_pulse.html.j2
```

## Scheduling Emails

Add to your crontab (`crontab -e`):

```bash
# Daily brief -- 7 AM PT weekdays
0 7 * * 1-5 /path/to/Slackhub/slackhubv1/.venv/bin/slack-hub email-digest --type daily

# Hourly pulse -- 11 AM through 5 PM PT weekdays
0 11-17 * * 1-5 /path/to/Slackhub/slackhubv1/.venv/bin/slack-hub email-digest --type hourly
```

Replace `/path/to/Slackhub` with your actual clone location (e.g. `~/dev/Slackhub`).

## Configuration

All settings live in `config/config.yaml`. Key sections:

- **channels** -- organized by priority tier (high/medium/low)
- **direct_messages** -- opt-in DM monitoring with allowlist
- **llm** -- per-task model selection across 4 providers (Google Gemini, OpenAI GPT, Anthropic Claude, Ollama local)
- **email** -- daily and hourly digest settings with smart suppression
- **todo** -- Google Sheets (via webhook URL or service account) and auto-complete settings

See `config/config.example.yaml` for the full template.

## Architecture

```
Slack API -> Ingestion -> SQLite -> Classification (LLM) -> Google Sheets (webhook or API)
                                                         -> Digest -> Email
```

Everything runs locally. No shared servers. Each user's instance only sees their own channels.

## LLM Cost

Each task is independently configurable. Example configurations at typical PM volumes (~300--500 msgs/day):

**Gemini + OpenAI (recommended if no Anthropic access):**

| Task | Model | ~Cost/Day |
|------|-------|-----------|
| Classification | Gemini 2.0 Flash | $0.02--$0.05 |
| TODO Extraction | GPT-4o-mini | $0.02--$0.06 |
| Summarization | GPT-4o | $0.10--$0.25 |
| Resolution Detection | Gemini 2.0 Flash | $0.01--$0.03 |
| **Total** | | **$0.15--$0.39** |

**Gemini + Anthropic:**

| Task | Model | ~Cost/Day |
|------|-------|-----------|
| Classification | Gemini 2.0 Flash | $0.02--$0.05 |
| TODO Extraction | Claude Haiku 4.5 | $0.03--$0.08 |
| Summarization | Claude Sonnet 4.5 | $0.10--$0.30 |
| Resolution Detection | Gemini 2.0 Flash | $0.01--$0.03 |
| **Total** | | **$0.16--$0.46** |

**All-OpenAI:**

| Task | Model | ~Cost/Day |
|------|-------|-----------|
| Classification | GPT-4o-mini | $0.02--$0.06 |
| TODO Extraction | GPT-4o-mini | $0.02--$0.06 |
| Summarization | GPT-4o | $0.10--$0.25 |
| Resolution Detection | GPT-4o-mini | $0.01--$0.03 |
| **Total** | | **$0.15--$0.40** |

## Security

- Slack tokens are user-scoped and stored locally
- LLM calls can be routed through an internal gateway (via `openai_base_url` for Azure/proxy setups), commercial APIs, or run locally via Ollama
- Google Sheets credentials are scoped to a single spreadsheet
- Apps Script webhook runs under your own Google account -- no shared infrastructure
- All credential files are excluded from version control

## License

MIT
