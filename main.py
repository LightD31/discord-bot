"""
Main script to run

This script initializes extensions and starts the bot
"""
import os
import sys

import interactions
from dotenv import load_dotenv

from config import DEBUG, DEV_GUILD
from src import logutil
from extensions.spotifyext import Spotify
from src.spotify import embed_message_vote


load_dotenv()

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
    debug_scope=DEV_GUILD,
    intents=interactions.Intents.ALL,
)


@interactions.listen()
async def on_startup():
    """Called when the bot starts"""
    logger.info(f"Logged in as {client.user}")
    Spotify.check_playlist_changes.start()
    Spotify.randomvote.start()


@interactions.listen()
async def on_component(event: interactions.api.events.Component):
    """Called when a component is clicked"""
    ctx = event.ctx
    embed_original = ctx.message.embeds[0]
    # Read the votes from the file into a dictionary
    if ctx.custom_id == "keep":
        txtvote = "conserver"
    else:
        txtvote = "supprimer"
    votes = {}
    with open("data/votes.txt", "r") as f:
        for line in f:
            user_id, vote = line.strip().split(":")
            votes[user_id] = vote

    # Check if the user has already voted and update their vote if necessary
    if str(ctx.user.id) in votes:
        old_vote = votes[str(ctx.user.id)]
        if old_vote == ctx.custom_id:
            await ctx.send(f"tu as déjà voté pour {txtvote} cette chanson !", ephemeral=True)
            logger.info(f"User {ctx.user.username} tried to vote twice")
            return
        votes[str(ctx.user.id)] = ctx.custom_id
        with open("data/votes.txt", "r+") as f:
            content = f.read()
            f.seek(0)
            f.write(content.replace(f"{ctx.user.id}:{old_vote}", f"{ctx.user.id}:{ctx.custom_id}"))
            f.truncate()
            logger.info(f"User {ctx.user.username} changed their vote to {ctx.custom_id}")

    # Add the user's vote to the file if they haven't voted yet
    else:
        with open("data/votes.txt", "a") as f:
            f.write(f"{ctx.user.id}:{ctx.custom_id}\n")
            logger.info(f"User {ctx.user.username} voted {ctx.custom_id}")
            votes[str(ctx.user.id)] = ctx.custom_id
    # Count the votes
    vote_counts = {}
    for vote in votes.values():
        if vote in vote_counts:
            vote_counts[vote] += 1
        else:
            vote_counts[vote] = 1
    # Count votes by adding up the number of lines with each vote
    keep = vote_counts.get("keep", 0)
    remove = vote_counts.get("remove", 0)
    await ctx.message.edit(
        embeds=[embed_original, await embed_message_vote(keep, remove)]
    )

    await ctx.send(f"Ton vote pour **{txtvote}** cette musique a bien été pris en compte ! 🗳️", ephemeral=True)


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
