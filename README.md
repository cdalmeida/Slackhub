# Slackhub

Slackhub bridges **Slack** and **GitHub** — receive GitHub notifications in Slack channels, create issues, review pull requests, and interact with your repositories directly from Slack.

## Features

- **GitHub → Slack notifications** for issues, pull requests, pushes, and releases
- **Slash commands** to create issues and inspect pull requests from Slack
- **Interactive buttons** to approve pull requests without leaving Slack
- **Automatic link expansion** — paste a GitHub issue or PR URL in Slack and get a rich summary
- Configurable per-repository Slack channel routing

## Architecture

```
Slack (events / commands)
        │
        ▼
  slack-bolt App ──► slack/handler.py   (message handler, slash commands, actions)
                          │
                          ▼
                   github/client.py     (GitHub REST API wrapper)

GitHub Webhooks
        │
        ▼
  Flask Route ──────► github/events.py  (webhook verification & dispatch)
                          │
                          ▼
                   slack/notifier.py    (posts formatted messages to Slack)
```

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/cdalmeida/Slackhub.git
cd Slackhub
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your Slack and GitHub credentials
```

### 3. Run

```bash
python app.py
# or with gunicorn for production:
gunicorn app:create_app --bind 0.0.0.0:3000
```

## Configuration

| Variable | Required | Description |
|---|---|---|
| `SLACK_BOT_TOKEN` | ✅ | Bot OAuth token (`xoxb-...`) |
| `SLACK_SIGNING_SECRET` | ✅ | Slack app signing secret |
| `GITHUB_TOKEN` | ✅ | GitHub personal access token |
| `GITHUB_WEBHOOK_SECRET` | ✅ | Secret for validating webhook payloads |
| `REPO_CHANNEL_MAP` | ✅ | Comma-separated `owner/repo:#channel` pairs |
| `PORT` | | HTTP port (default `3000`) |
| `DEBUG` | | Enable debug mode (default `false`) |

## Slack App Setup

1. Create a new Slack app at <https://api.slack.com/apps>
2. Enable **Event Subscriptions** — set the Request URL to `https://your-host/slack/events`
3. Subscribe to bot events: `message.channels`, `message.groups`
4. Add **Slash Commands**: `/gh-issue` and `/gh-pr` pointing to `https://your-host/slack/events`
5. Enable **Interactivity** — set the Request URL to `https://your-host/slack/events`
6. Install the app to your workspace and copy the **Bot User OAuth Token**

## GitHub Webhook Setup

1. Go to your repository → **Settings → Webhooks → Add webhook**
2. Payload URL: `https://your-host/github/webhook`
3. Content type: `application/json`
4. Secret: the value of `GITHUB_WEBHOOK_SECRET`
5. Select individual events: _Issues_, _Pull requests_, _Pushes_, _Releases_, _Issue comments_, _Pull request reviews_

## Slash Commands

| Command | Description |
|---|---|
| `/gh-issue owner/repo Bug title` | Create a new GitHub issue |
| `/gh-pr owner/repo 42` | Show details of pull request #42 |

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

## License

MIT
