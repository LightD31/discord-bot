"""
Main script to run

This script initializes extensions and starts the bot
"""

import os
import sys

import interactions
from dotenv import load_dotenv

from config import DEBUG
from src import logutil

load_dotenv()

DEV_GUILD = os.environ.get("DEV_GUILD")

# Configure logging for this main.py handler
logger = logutil.init_logger("main.py")
logger.debug(
    "Debug mode is %s; This is not a warning, \
just an indicator. You may safely ignore",
    DEBUG,
)

if not os.environ.get("TOKEN"):
    logger.critical("TOKEN variable not set. Cannot continue")
    sys.exit(1)

client = interactions.Client(
    token=os.environ.get("TOKEN"),
    intents=interactions.Intents.ALL,
    send_not_ready_messages=True,
    delete_unused_application_cmds=True,
    auto_defer=True,
    send_command_tracebacks=False,
)


@interactions.listen()
async def on_startup():
    """Called when the bot starts"""
    logger.info(f"Logged in as {client.user}")


# get all python files in "extensions" folder
extensions = [
    f"extensions.{f[:-3]}"
    for f in os.listdir("extensions")
    if f.endswith(".py") and not f.startswith("_")
]
for extension in extensions:
    try:
        client.load_extension(extension)
        logger.info(f"Loaded extension {extension}")
    except interactions.errors.ExtensionLoadException as e:
        logger.exception(f"Failed to load extension {extension}.", exc_info=e)
client.start()
