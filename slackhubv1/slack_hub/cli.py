"""Slack Intelligence Hub CLI — main entrypoint."""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.markdown import Markdown
from rich.panel import Panel

from .config import load_config, save_config, Config
from .db import Database, get_database

console = Console()
logger = logging.getLogger("slack_hub")


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def get_config_and_db(config_path: str | None = None) -> tuple[Config, Database]:
    """Load config and initialize database."""
    config = load_config(config_path)
    setup_logging(config.log_level)
    db = get_database(config)
    return config, db


# ── Main group ──────────────────────────────────────────────────────────────

@click.group()
@click.option("--config", "config_path", default=None, help="Path to config.yaml")
@click.pass_context
def cli(ctx, config_path):
    """Slack Intelligence Hub — Automated Slack triage & TODO management."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path


# ── Database init ───────────────────────────────────────────────────────────

@cli.group("db")
def db_group():
    """Database management commands."""
    pass


@db_group.command("init")
@click.pass_context
def db_init(ctx):
    """Initialize the SQLite database."""
    config = load_config(ctx.obj.get("config_path"))
    db = get_database(config)
    db.init_schema()
    console.print(f"[green]✓[/green] Database initialized at {config.db_path_resolved}")


# ── Init wizard ─────────────────────────────────────────────────────────────

@cli.command()
@click.pass_context
def init(ctx):
    """Interactive setup wizard — configure credentials and settings."""
    console.print(Panel("Slack Intelligence Hub Setup", style="bold blue"))
    console.print()

    config = load_config(ctx.obj.get("config_path"))

    # Slack token
    token = click.prompt(
        "Slack token (from 'slack auth token' or SLACK_TOKEN env var)",
        default=config.slack_token or "",
        show_default=False,
    )
    config.slack_token = token

    # User ID
    if token and not config.user_id:
        try:
            from slack_sdk import WebClient
            client = WebClient(token=token)
            auth = client.auth_test()
            config.user_id = auth["user_id"]
            config.user_display_name = auth.get("user", "")
            console.print(f"[green]✓[/green] Authenticated as {config.user_display_name} ({config.user_id})")
        except Exception as e:
            console.print(f"[yellow]⚠[/yellow] Could not auto-detect user: {e}")
            config.user_id = click.prompt("Your Slack user ID (e.g., U0XXXXXXX)")
            config.user_display_name = click.prompt("Your display name")
    elif not config.user_id:
        config.user_id = click.prompt("Your Slack user ID")
        config.user_display_name = click.prompt("Your display name")

    # LLM API keys
    console.print()
    console.print("[bold]LLM Configuration[/bold]")
    console.print("  Configure at least one provider. You can mix providers per task.")
    console.print()
    config.llm.anthropic_api_key = click.prompt(
        "Anthropic API key (or Enter to skip / use ANTHROPIC_API_KEY env var)",
        default=config.llm.anthropic_api_key or "",
        show_default=False,
    )
    config.llm.google_api_key = click.prompt(
        "Google AI API key (or Enter to skip / use GOOGLE_API_KEY env var)",
        default=config.llm.google_api_key or "",
        show_default=False,
    )
    config.llm.openai_api_key = click.prompt(
        "OpenAI API key (or Enter to skip / use OPENAI_API_KEY env var)",
        default=config.llm.openai_api_key or "",
        show_default=False,
    )
    if config.llm.openai_api_key:
        config.llm.openai_base_url = click.prompt(
            "OpenAI base URL (for Azure/proxy, or Enter for default)",
            default=config.llm.openai_base_url or "",
            show_default=False,
        )

    # Google Sheets
    console.print()
    console.print("[bold]Google Sheets TODO List[/bold]")
    console.print("  Choose how to connect to Google Sheets:")
    console.print("  [1] Apps Script webhook (no service account needed)")
    console.print("  [2] Service account (requires Google Cloud project)")
    console.print("  [3] Skip (use local TODO list only)")
    sheets_choice = click.prompt(
        "  Option",
        type=click.Choice(["1", "2", "3"]),
        default="3",
        show_default=True,
    )
    if sheets_choice == "1":
        console.print()
        console.print("  To set up the webhook:")
        console.print("  1. Create a Google Sheet")
        console.print("  2. Extensions > Apps Script")
        console.print("  3. Paste the script from slack_hub/apps_script.js")
        console.print("  4. Deploy > New Deployment > Web app")
        console.print("  5. Execute as: Me, Access: Anyone")
        console.print("  6. Copy the deployment URL")
        console.print()
        config.todo.webhook_url = click.prompt(
            "  Apps Script deployment URL",
            default=config.todo.webhook_url or "",
            show_default=False,
        )
        config.todo.sheet_id = ""
    elif sheets_choice == "2":
        config.todo.sheet_id = click.prompt(
            "  Google Sheet ID (from the URL)",
            default=config.todo.sheet_id or "",
            show_default=False,
        )
        config.todo.webhook_url = ""
    else:
        config.todo.sheet_id = ""
        config.todo.webhook_url = ""

    # Email
    console.print()
    console.print("[bold]Email Digest[/bold]")
    config.email.recipient = click.prompt(
        "Work email for digests",
        default=config.email.recipient or "",
        show_default=False,
    )

    # Save
    config_path = ctx.obj.get("config_path") or "config/config.yaml"
    save_config(config, config_path)
    console.print()
    console.print(f"[green]✓[/green] Configuration saved to {config_path}")

    # Init DB
    db = get_database(config)
    db.init_schema()
    console.print(f"[green]✓[/green] Database initialized")
    console.print()
    console.print("Next: run [bold]slack-hub channels setup[/bold] to pick your channels.")


# ── Channel management ──────────────────────────────────────────────────────

@cli.group("channels")
def channels_group():
    """Channel configuration commands."""
    pass


@channels_group.command("list")
@click.pass_context
def channels_list(ctx):
    """List configured channels."""
    config = load_config(ctx.obj.get("config_path"))

    table = Table(title="Configured Channels")
    table.add_column("Tier", style="bold")
    table.add_column("Name")
    table.add_column("ID", style="dim")

    for tier in ["high_priority", "medium_priority", "low_priority"]:
        for ch in config.channels.get(tier, []):
            tier_color = {"high_priority": "red", "medium_priority": "yellow", "low_priority": "blue"}
            table.add_row(f"[{tier_color.get(tier, 'white')}]{tier}[/]", ch.name, ch.id)

    if config.direct_messages.enabled:
        for dm in config.direct_messages.allowlist:
            table.add_row("[magenta]dm[/]", dm.name, dm.id)

    console.print(table)


@channels_group.command("setup")
@click.pass_context
def channels_setup(ctx):
    """Interactive channel picker — select channels and assign tiers."""
    config, db = get_config_and_db(ctx.obj.get("config_path"))

    from .ingestion import SlackIngester
    ingester = SlackIngester(config, db)

    channels = None
    api_restricted = False

    console.print("Fetching your channels from Slack...")
    try:
        channels = ingester.list_user_channels()
    except Exception as exc:
        if "enterprise_is_restricted" in str(exc):
            api_restricted = True
            console.print(
                "\n[yellow]⚠  Your Slack workspace restricts channel listing APIs.[/yellow]"
            )
            console.print("Switching to manual entry mode.\n")
        else:
            raise

    selected = {"high_priority": [], "medium_priority": [], "low_priority": []}

    if api_restricted or not channels:
        _manual_channel_setup(selected)
    else:
        console.print(f"\nFound {len(channels)} channels. Select ones to monitor:\n")

        for i, ch in enumerate(channels[:40]):
            console.print(
                f"  [{i+1:2d}] {ch['name']} ({ch['num_members']} members)"
                f"{'  — ' + ch['topic'][:50] if ch['topic'] else ''}"
            )

        console.print()
        console.print("Enter channel numbers separated by commas for each tier.")
        console.print("Press Enter to skip a tier.\n")

        for tier, label in [
            ("high_priority", "High priority (polled every 10 min)"),
            ("medium_priority", "Medium priority (polled every 30 min)"),
            ("low_priority", "Low priority (polled every 60 min)"),
        ]:
            raw = click.prompt(f"  {label}", default="", show_default=False)
            if raw.strip():
                indices = [int(x.strip()) - 1 for x in raw.split(",") if x.strip().isdigit()]
                for idx in indices:
                    if 0 <= idx < len(channels):
                        ch = channels[idx]
                        from .config import ChannelEntry
                        selected[tier].append(ChannelEntry(name=ch["name"], id=ch["id"]))

    config.channels = selected

    # DM setup
    if not api_restricted and click.confirm(
        "\nAlso configure direct message monitoring?", default=False
    ):
        config.direct_messages.enabled = True
        try:
            dms = ingester.list_user_dms()
        except Exception:
            dms = []
        if dms:
            console.print(f"\nFound {len(dms)} DM conversations:\n")
            for i, dm in enumerate(dms[:20]):
                console.print(f"  [{i+1:2d}] {dm['name']} ({dm['type']})")
            raw = click.prompt("\nEnter numbers to monitor", default="", show_default=False)
            if raw.strip():
                indices = [int(x.strip()) - 1 for x in raw.split(",") if x.strip().isdigit()]
                from .config import DMEntry
                config.direct_messages.allowlist = [
                    DMEntry(name=dms[i]["name"], id=dms[i]["id"])
                    for i in indices if 0 <= i < len(dms)
                ]
            use_llm = click.confirm("Send DM content through external LLM?", default=True)
            config.direct_messages.use_llm = use_llm

    config_path = ctx.obj.get("config_path") or "config/config.yaml"
    save_config(config, config_path)

    total = sum(len(v) for v in selected.values())
    dm_count = len(config.direct_messages.allowlist)
    console.print(f"\n[green]✓[/green] Saved {total} channels and {dm_count} DMs to {config_path}")


def _manual_channel_setup(selected: dict) -> None:
    """Prompt the user to manually enter channel names and IDs."""
    from .config import ChannelEntry

    console.print("To find a channel ID in Slack:")
    console.print("  1. Right-click a channel name → 'View channel details'")
    console.print("  2. Scroll to the bottom — the Channel ID is shown (e.g. C01AB2CDE)")
    console.print("  Or: right-click → 'Copy link' — the ID is the last segment of the URL.\n")

    for tier, label in [
        ("high_priority", "High priority (polled every 10 min)"),
        ("medium_priority", "Medium priority (polled every 30 min)"),
        ("low_priority", "Low priority (polled every 60 min)"),
    ]:
        console.print(f"[bold]{label}[/bold]")
        console.print("Enter channels one per line as:  #channel-name  CHANNEL_ID")
        console.print("Leave blank and press Enter when done.\n")

        while True:
            line = click.prompt(f"  {tier}", default="", show_default=False)
            if not line.strip():
                break
            parts = line.strip().split()
            if len(parts) >= 2:
                name = parts[0] if parts[0].startswith("#") else f"#{parts[0]}"
                ch_id = parts[1]
                selected[tier].append(ChannelEntry(name=name, id=ch_id))
                console.print(f"    [green]+ Added {name} ({ch_id})[/green]")
            elif len(parts) == 1:
                val = parts[0]
                if val.startswith("C") and len(val) >= 9:
                    selected[tier].append(ChannelEntry(name=val, id=val))
                    console.print(f"    [green]+ Added {val} (name will resolve on first fetch)[/green]")
                else:
                    name = val if val.startswith("#") else f"#{val}"
                    console.print(
                        f"    [yellow]Need the channel ID too. "
                        f"Enter as: {name} C01XXXXXXX[/yellow]"
                    )
        console.print()


# ── Fetch ───────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--tier", type=click.Choice(["high_priority", "medium_priority", "low_priority"]))
@click.option("--hours", type=int, default=None, help="Lookback hours for first run")
@click.pass_context
def fetch(ctx, tier, hours):
    """Fetch messages from configured Slack channels."""
    config, db = get_config_and_db(ctx.obj.get("config_path"))

    from .ingestion import SlackIngester
    ingester = SlackIngester(config, db)

    with console.status("Fetching from Slack..."):
        stats = ingester.run(tier=tier, lookback_hours=hours)

    dm_note = f" and {stats['dms']} DMs" if stats.get('dms') else ""
    console.print(
        f"[green]✓[/green] Fetched {stats['messages']} messages, "
        f"{stats['threads']} threads from {stats['channels']} channels"
        f"{dm_note}"
    )


# ── Classify ────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--dry-run", is_flag=True, help="Preview without writing to DB")
@click.pass_context
def classify(ctx, dry_run):
    """Run LLM classification on unclassified threads."""
    config, db = get_config_and_db(ctx.obj.get("config_path"))

    from .classifier import Classifier
    from .sheets import get_sheets_manager

    # Get corrections from sheet for feedback loop
    sheets = get_sheets_manager(config, db)
    corrections = sheets.get_corrections()

    classifier = Classifier(config, db)

    with console.status("Classifying threads..."):
        stats = classifier.classify_unclassified(
            corrections=corrections, dry_run=dry_run
        )

    if dry_run:
        console.print("[yellow]DRY RUN[/yellow] — no changes written.")

    if stats:
        table = Table(title="Classification Results")
        table.add_column("Category")
        table.add_column("Count", justify="right")
        for cat, count in sorted(stats.items()):
            table.add_row(cat, str(count))
        console.print(table)
    else:
        console.print("No threads to classify.")


# ── Digest ──────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--hours", type=int, default=None, help="Lookback window in hours")
@click.option("--send-dm", is_flag=True, help="Also send as Slack DM to self")
@click.pass_context
def digest(ctx, hours, send_dm):
    """Full pipeline: fetch → classify → generate digest."""
    config, db = get_config_and_db(ctx.obj.get("config_path"))

    from .ingestion import SlackIngester
    from .classifier import Classifier
    from .sheets import get_sheets_manager
    from .digest import DigestGenerator

    # Step 1: Fetch
    console.print("[bold]Step 1:[/bold] Fetching from Slack...")
    ingester = SlackIngester(config, db)
    fetch_stats = ingester.run(lookback_hours=hours)
    console.print(
        f"  Fetched {fetch_stats['messages']} messages from "
        f"{fetch_stats['channels']} channels"
    )

    # Step 2: Classify
    console.print("[bold]Step 2:[/bold] Classifying threads...")
    sheets = get_sheets_manager(config, db)
    corrections = sheets.get_corrections()
    classifier = Classifier(config, db)
    cls_stats = classifier.classify_unclassified(corrections=corrections)
    console.print(f"  Classified: {cls_stats}")

    # Step 3: Sync TODOs to sheet
    console.print("[bold]Step 3:[/bold] Syncing TODOs...")
    sync_stats = sheets.sync_todos()
    console.print(f"  Sheet sync: {sync_stats}")

    # Step 4: Generate digest
    console.print("[bold]Step 4:[/bold] Generating digest...")
    generator = DigestGenerator(config, db)
    markdown = generator.generate(hours=hours)

    console.print()
    console.print(Markdown(markdown))

    # Optional: DM to self
    if send_dm and config.slack_token:
        try:
            from slack_sdk import WebClient
            client = WebClient(token=config.slack_token)
            client.chat_postMessage(channel=config.user_id, text=markdown)
            console.print("\n[green]✓[/green] Digest sent as Slack DM.")
        except Exception as e:
            console.print(f"\n[red]✗[/red] Failed to DM: {e}")


# ── TODOs ───────────────────────────────────────────────────────────────────

@cli.group("todos")
def todos_group():
    """TODO list management."""
    pass


@todos_group.command("list")
@click.option("--all", "show_all", is_flag=True, help="Include done/stale/dismissed")
@click.option("--urgency", type=click.Choice(["high", "medium", "low"]))
@click.pass_context
def todos_list(ctx, show_all, urgency):
    """Show open TODOs."""
    config, db = get_config_and_db(ctx.obj.get("config_path"))

    todos = db.get_all_todos() if show_all else db.get_open_todos()
    if urgency:
        todos = [t for t in todos if t.get("urgency") == urgency]

    if not todos:
        console.print("No TODOs found.")
        return

    table = Table(title="TODOs")
    table.add_column("ID", style="bold")
    table.add_column("Urgency")
    table.add_column("Title")
    table.add_column("Due")
    table.add_column("Status")

    for todo in todos:
        urg = todo.get("urgency", "medium")
        urg_color = {"high": "red", "medium": "yellow", "low": "blue"}.get(urg, "white")
        status = todo.get("status", "open")
        table.add_row(
            f"TODO-{todo['id']:04d}",
            f"[{urg_color}]{urg}[/]",
            todo.get("title", "")[:60],
            todo.get("due_date", "") or "—",
            status,
        )

    console.print(table)


@todos_group.command("done")
@click.argument("todo_id", type=int)
@click.pass_context
def todos_done(ctx, todo_id):
    """Mark a TODO as complete."""
    config, db = get_config_and_db(ctx.obj.get("config_path"))
    db.update_todo_status(todo_id, "done")
    console.print(f"[green]✓[/green] TODO-{todo_id:04d} marked as done.")


@todos_group.command("dismiss")
@click.argument("todo_id", type=int)
@click.pass_context
def todos_dismiss(ctx, todo_id):
    """Dismiss a TODO as not relevant."""
    config, db = get_config_and_db(ctx.obj.get("config_path"))
    db.update_todo_status(todo_id, "dismissed")
    console.print(f"[green]✓[/green] TODO-{todo_id:04d} dismissed.")


@todos_group.command("refresh")
@click.pass_context
def todos_refresh(ctx):
    """Re-scan threads for auto-resolution of open TODOs."""
    config, db = get_config_and_db(ctx.obj.get("config_path"))

    from .classifier import Classifier
    classifier = Classifier(config, db)

    with console.status("Checking for resolved TODOs..."):
        resolved = classifier.check_resolutions()
        stale = classifier.mark_stale()

    console.print(f"[green]✓[/green] {resolved} TODOs auto-resolved, {stale} marked stale.")


# ── Email digest ────────────────────────────────────────────────────────────

@cli.command("email-digest")
@click.option("--type", "digest_type", type=click.Choice(["daily", "hourly"]), required=True)
@click.pass_context
def email_digest(ctx, digest_type):
    """Generate and send an email digest."""
    config, db = get_config_and_db(ctx.obj.get("config_path"))

    from .email_digest import EmailDigest
    emailer = EmailDigest(config, db)

    if digest_type == "daily":
        success = emailer.send_daily_brief()
    else:
        success = emailer.send_hourly_pulse()

    if success:
        console.print(f"[green]✓[/green] {digest_type.title()} digest sent to {config.email.recipient}")
    else:
        console.print(f"[yellow]⚠[/yellow] {digest_type.title()} digest not sent (check logs).")


# ── Watch (background mode) ────────────────────────────────────────────────

@cli.command()
@click.option("--daemon", is_flag=True, help="Detach from terminal")
@click.pass_context
def watch(ctx, daemon):
    """Background polling mode — continuous fetch and classify."""
    config, db = get_config_and_db(ctx.obj.get("config_path"))

    from .ingestion import SlackIngester
    from .classifier import Classifier
    from .sheets import get_sheets_manager

    ingester = SlackIngester(config, db)
    classifier = Classifier(config, db)
    sheets = get_sheets_manager(config, db)

    console.print("[bold]Slack Hub[/bold] — watch mode started. Press Ctrl+C to stop.\n")

    cycle = 0
    classify_interval = 3  # Classify every 3rd fetch cycle

    try:
        while True:
            cycle += 1
            now = datetime.now()
            console.print(f"[dim]{now.strftime('%H:%M:%S')}[/dim] Cycle {cycle}...")

            # Fetch
            try:
                stats = ingester.run()
                console.print(
                    f"  Fetched {stats['messages']} msgs, {stats['threads']} threads"
                )
            except Exception as e:
                console.print(f"  [red]Fetch error:[/red] {e}")

            # Classify every Nth cycle
            if cycle % classify_interval == 0:
                try:
                    corrections = sheets.get_corrections()
                    cls_stats = classifier.classify_unclassified(corrections=corrections)
                    if cls_stats:
                        console.print(f"  Classified: {cls_stats}")
                    sheets.sync_todos()
                except Exception as e:
                    console.print(f"  [red]Classify error:[/red] {e}")

            # Sleep based on highest-frequency tier
            sleep_min = min(
                t.interval_min for t in config.polling_tiers.values()
            )
            console.print(f"  Sleeping {sleep_min} min...")
            time.sleep(sleep_min * 60)

    except KeyboardInterrupt:
        console.print("\n[bold]Watch mode stopped.[/bold]")


# ── Stats ───────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--days", type=int, default=1, help="Lookback period in days")
@click.pass_context
def stats(ctx, days):
    """Show activity statistics and classification breakdown."""
    config, db = get_config_and_db(ctx.obj.get("config_path"))

    end = datetime.utcnow()
    start = end - timedelta(days=days)

    activity = db.compute_activity_stats(start, end, config.user_id)

    table = Table(title=f"Activity Stats (last {days} day{'s' if days != 1 else ''})")
    table.add_column("Metric")
    table.add_column("Value", justify="right")

    table.add_row("Messages sent", str(activity["messages_sent"]))
    table.add_row("Messages received", str(activity["messages_received"]))
    table.add_row("Direct @mentions", str(activity["direct_mentions"]))
    table.add_row("Threads tagged", str(activity["threads_tagged"]))
    table.add_row("Awaiting response", str(activity["threads_awaiting_response"]))
    table.add_row("TODOs created", str(activity["todos_created"]))
    table.add_row("TODOs resolved", str(activity["todos_resolved"]))

    console.print(table)

    if activity["channel_volumes"]:
        ch_table = Table(title="Channel Volumes")
        ch_table.add_column("Channel")
        ch_table.add_column("Messages", justify="right")
        for ch, count in sorted(
            activity["channel_volumes"].items(), key=lambda x: x[1], reverse=True
        ):
            ch_table.add_row(ch, str(count))
        console.print(ch_table)

    # TODO stats
    open_todos = db.get_open_todos()
    all_todos = db.get_all_todos()
    console.print(f"\nTODOs: {len(open_todos)} open / {len(all_todos)} total")


# ── Entry point ─────────────────────────────────────────────────────────────

def main():
    cli(obj={})


if __name__ == "__main__":
    main()
