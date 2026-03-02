# Slack Intelligence Hub

Automated Slack triage, TODO management, and activity digests for busy product managers.

`slack-hub` continuously monitors your Slack channels, classifies threads by relevance and urgency using LLMs, maintains an auto-updated TODO list in Google Sheets, and delivers scheduled email digests.

## Quick Start

```bash
git clone https://github.com/cdalmeida/Slackhub.git
cd Slackhub/slackhubv1
make install
source .venv/bin/activate
slack-hub init
slack-hub channels setup
slack-hub digest
```

## Prerequisites

- **Python 3.12** -- `brew install python@3.12` on macOS
- **Slack CLI** -- `curl -fsSL https://downloads.slack-edge.com/slack-cli/install.sh | bash`
- **At least one LLM API key** (OpenAI, Anthropic, Google AI, or Ollama)
- **Google Sheets** (optional) via Apps Script webhook or service account

**Enterprise Grid users**: If your workspace restricts channel listing APIs, `channels setup` will switch to manual entry mode where you enter channel names and IDs directly.

See [`slackhubv1/README.md`](slackhubv1/README.md) for full documentation, architecture, commands, and configuration.
