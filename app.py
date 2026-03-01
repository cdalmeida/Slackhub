"""
Slackhub - Slack and GitHub Integration
Main application entry point
"""

import os
import logging
from flask import Flask
from slack_sdk.web import WebClient
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler

from config import Config
from slack.handler import register_slack_handlers
from github.events import register_github_routes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


def create_app(config: Config = None) -> Flask:
    """Create and configure the Flask application."""
    if config is None:
        config = Config.from_env()

    bolt_app = App(
        token=config.slack_bot_token,
        signing_secret=config.slack_signing_secret,
    )

    register_slack_handlers(bolt_app)

    flask_app = Flask(__name__)
    flask_app.config["SLACKHUB_CONFIG"] = config

    handler = SlackRequestHandler(bolt_app)

    @flask_app.route("/slack/events", methods=["POST"])
    def slack_events():
        return handler.handle(flask_app.current_request if hasattr(flask_app, "current_request") else None)

    register_github_routes(flask_app, config)

    return flask_app


if __name__ == "__main__":
    cfg = Config.from_env()
    app = create_app(cfg)
    port = int(os.environ.get("PORT", 3000))
    logger.info(f"Starting Slackhub on port {port}")
    app.run(host="0.0.0.0", port=port, debug=cfg.debug)
