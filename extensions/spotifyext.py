import io
import json
import os
import random
from datetime import datetime, timedelta
import time

import interactions
import pymongo
import pytz
import requests
import spotipy
from dotenv import load_dotenv

from dict import finishList, startList, discord2name
from src import logutil
from src.spotify import *
from src.utils import milliseconds_to_string

load_dotenv()

# Load environment variables
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.environ.get("SPOTIFY_REDIRECT_URI")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID"))
PLAYLIST_ID = os.environ.get("PLAYLIST_ID")
PATCH_MESSAGE_URL = os.environ.get("PATCH_MESSAGE_URL")
LOG_CHANNEL_ID = os.environ.get("LOG_CHANNEL_ID")
GUILDE_GUILD_ID = int(os.environ.get("GUILDE_GUILD_ID"))
DEV_GUILD = int(os.environ.get("DEV_GUILD"))
MONGO_SERV = os.environ.get("MONGO_SERV")
COOLDOWN_TIME = 5
REMINDERS_FILE = os.environ.get("REMINDERS_FILE")

# Change this if you'd like - this labels log messages for debug mode
logger = logutil.init_logger(os.path.basename(__file__))

# Connect to MongoDB
client = pymongo.MongoClient(MONGO_SERV)
db = client["Playlist"]
playlistItemsFull = db["playlistItemsFull"]
votesDB = db["votes"]

# Authenticate with Spotify API
sp = spotify_auth()

# Keep track of last votes
last_votes = {}
# Keep track of reminders
reminders = {}
#keep track of vote infos
vote_infos = {}
#keep track of snapshot
snapshot = {}


class Spotify(interactions.Extension):
    def __init__(self, bot: interactions.client):
        self.bot = bot

    @interactions.listen()
    async def on_startup(self):
        # Start background tasks
        self.check_playlist_changes.start()
        self.randomvote.start()

    @interactions.listen()
    async def on_ready(self):
        await self.load_reminders()
        self.reminder_check.start()
        await self.load_voteinfos()

    @interactions.slash_command(
        "addsong",
        description="Ajoute une chanson à la playlist de la guilde.",
        scopes=[GUILDE_GUILD_ID],
    )
    @interactions.slash_option(
        name="song",
        description="Nom de la chanson à ajouter",
        opt_type=interactions.OptionType.STRING,
        required=True,
        autocomplete=True,
    )
    async def addsong(self, ctx: interactions.SlashContext, song):
        """
        Add a song to the guild's playlist.
        """
        await self.bot.change_presence(status=interactions.Status.ONLINE)
        if ctx.channel_id == CHANNEL_ID:
            # Get last track IDs from MongoDB
            last_track_ids = playlistItemsFull.distinct("_id")
            logger.info(f"/addsong '{song}' utilisé par {ctx.author.username}")
            try:
                # Get track info from Spotify API
                track = sp.track(song, market="FR")
                song = spotifymongoformat(track, ctx.author)
            except spotipy.exceptions.SpotifyException:
                await ctx.send("Cette chanson n'existe pas.", ephemeral=True)
                logger.info("Commande /addsong utilisée avec une chanson inexistante")
            if song["_id"] not in last_track_ids:
                # Add song to MongoDB and Spotify playlist
                playlistItemsFull.insert_one(song)
                sp.playlist_add_items(PLAYLIST_ID, [song["_id"]])
                # Create and send embed message
                embed = await embed_song(
                    song=song,
                    track=track,
                    type=Type.ADD,
                    time=interactions.Timestamp.utcnow(),
                    person=ctx.author.username,
                    icon=ctx.author.avatar.url,
                )
                await ctx.send(
                    content=f"{random.choice(startList)} {ctx.author.mention}, {random.choice(finishList)}",
                    embeds=embed,
                )
                logger.info(f"{track['name']} ajouté par {ctx.author.display_name}")
            else:
                await ctx.send(
                    "Cette chanson a déjà été ajoutée à la playlist.", ephemeral=True
                )
                logger.info("Commande /addsong utilisée avec une chanson déjà présente")
        else:
            await ctx.send(
                "Vous ne pouvez pas utiliser cette commande dans ce salon.",
                ephemeral=True,
            )
            logger.info(
                f"Commande /addsong utilisée dans un mauvais salon({ctx.channel.name})"
            )
        await self.bot.change_presence(status=interactions.Status.IDLE)

    @addsong.autocomplete("song")
    async def autocomplete(self, ctx: interactions.AutocompleteContext):
        """
        Autocomplete function for the 'addsong' command.
        """
        if not ctx.input_text:
            choices = [
                {
                    "name": "Veuillez entrer un nom de chanson",
                    "value": "error",
                }
            ]
        else:
            # Search for tracks on Spotify
            items = sp.search(ctx.input_text, limit=10, type="track", market="FR")[
                "tracks"
            ]["items"]
            if not items:
                choices = [
                    {
                        "name": "Aucun résultat",
                        "value": "error",
                    }
                ]
            else:
                # Format search results for autocomplete choices
                choices = [
                    {
                        "name": f"{item['artists'][0]['name']} - {item['name']} (Album: {item['album']['name']})"[
                            :100
                        ],
                        "value": item["uri"],
                    }
                    for item in items
                ]
        await ctx.send(choices=choices)

    @interactions.Task.create(interactions.TimeTrigger(hour=20, minute=00, utc=False))
    async def randomvote(self):
        logger.info("Tache randomvote lancée")
        with open("data/voteinfos.json", "r") as f:
            vote_infos = json.load(f)
        message_id = vote_infos.get("message_id")
        track_id = vote_infos.get("track_id")
        logger.debug(f"message_id: {message_id}")
        logger.debug(f"track_id: {track_id}")
        channel = self.bot.get_channel(CHANNEL_ID)
        message = await channel.fetch_message(message_id)
        logger.debug(f"message : {str(message.id)}")
        votes = votesDB.find_one({"_id": track_id})
        conserver, supprimer, menfou, users = count_votes(votes["votes"])

        logger.debug(
            f"keep : {str(conserver)}\nremove : {str(supprimer)}\nmenfou : {str(menfou)}"
        )
        song = playlistItemsFull.find_one({"_id": track_id})
        track = sp.track(song["_id"], market="FR")
        await message.unpin()
        if supprimer > conserver or (conserver == 0 and supprimer == 0 and menfou >= 2):
            await message.edit(
                content="La chanson a été supprimée.",
                embeds=[
                    await embed_song(
                        song=song,
                        track=track,
                        type=Type.VOTE_LOSE,
                        time=interactions.Timestamp.now(),
                    ),
                    await embed_message_vote(
                        keep=conserver,
                        remove=supprimer,
                        menfou=menfou,
                        color=interactions.MaterialColors.DEEP_ORANGE,
                    ),
                ],
                components=[],
            )
            sp.playlist_remove_all_occurrences_of_items(PLAYLIST_ID, [track_id])
            playlistItemsFull.delete_one({"_id": track_id})
            votesDB.find_one_and_update(
                {"_id": track_id}, {"$set": {"state": "supprimée"}}
            )
            logger.info("La chanson a été supprimée.")
            await Spotify.check_playlist_changes()
        else:
            await message.edit(
                content="La chanson a été conservée.",
                embeds=[
                    await embed_song(
                        song=song,
                        track=track,
                        type=Type.VOTE_WIN,
                        time=interactions.Timestamp.utcnow(),
                    ),
                    await embed_message_vote(
                        keep=conserver,
                        remove=supprimer,
                        menfou=menfou,
                        color=interactions.MaterialColors.LIME,
                    ),
                ],
                components=[],
            )
            votesDB.find_one_and_update(
                {"_id": track_id}, {"$set": {"state": "conservée"}}
            )
            logger.info("La chanson a été conservée.")
        track_ids = set(playlistItemsFull.distinct("_id"))
        pollhistory = set(votesDB.distinct("_id"))
        track_id = random.choice(list(track_ids))
        logger.debug(f"track_id choisie : {track_id}")
        while track_id in pollhistory:
            logger.warning(
                f"Chanson déjà votée, nouvelle chanson tirée au sort ({track_id})"
            )
            track_id = random.choice(list(track_ids))
        logger.info(f"Chanson tirée au sort : {track_id}")
        song = playlistItemsFull.find_one({"_id": track_id})
        track = sp.track(song["_id"], market="FR")
        logger.info("--------------------votedone--------------------")
        channel = await self.bot.fetch_channel(CHANNEL_ID)
        message = await channel.send(
            content=f"Voulez-vous conserver cette chanson dans playlist ? (poke <@{song['added_by']}>)",
            embeds=[
                await embed_song(
                    song=song,
                    track=track,
                    type=Type.VOTE,
                    time=str(self.randomvote.next_run),
                ),
                # await embed_message_vote(),
            ],
            components=[
                interactions.ActionRow(
                    interactions.Button(
                        label="Conserver",
                        style=interactions.ButtonStyle.SUCCESS,
                        emoji="✅",
                        custom_id="conserver",
                    ),
                    interactions.Button(
                        label="Supprimer",
                        style=interactions.ButtonStyle.DANGER,
                        emoji="🗑️",
                        custom_id="supprimer",
                    ),
                    interactions.Button(
                        label="Menfou",
                        style=interactions.ButtonStyle.SECONDARY,
                        emoji="🤷",
                        custom_id="menfou",
                    ),
                )
            ],
        )
        await message.pin()
        await channel.purge(deletion_limit=1, after=message)
        with open("data/voteinfos.json", "w") as f:
            json.dump({"message_id": str(message.id), "track_id": track_id}, f)
        votesDB.update_one(
            {"_id": track_id},
            {
                "$set": {
                    "name": f"{', '.join(artist['name'] for artist in track['artists'])} - {track['name']}",
                    "date": datetime.now().strftime("%Y-%m-%d"),
                }
            },
            upsert=True,
        )

    @interactions.listen()
    async def on_component(self, event: interactions.api.events.Component):
        """Called when a component is clicked"""
        ctx = event.ctx
        # Check if the user has voted recently
        user_id = str(ctx.user.id)
        if user_id in last_votes and time.time() - last_votes[user_id] < COOLDOWN_TIME:
            await ctx.send(
                "Tu ne peux voter que toutes les 5 secondes ⚠️", ephemeral=True
            )
            logger.warning(f"{ctx.user.username} a essayé de voter trop rapidement")
            return
        last_votes[user_id] = time.time()
        with open("data/voteinfos.json", "r") as f:
            vote_infos = json.load(f)
        message_id = vote_infos.get("message_id")
        track_id = vote_infos.get("track_id")
        if ctx.message.id == int(message_id):
            embed_original = ctx.message.embeds[0]
            # Check if the user has already voted and update their vote if necessary
            user_id = str(ctx.user.id)
            votes = votesDB.find_one_and_update(
                {"_id": track_id},
                {"$set": {f"votes.{user_id}": ctx.custom_id}},
                upsert=True,
                return_document=pymongo.ReturnDocument.AFTER,
            )
            logger.info(f"User {ctx.user.username} voted {ctx.custom_id}")
            # Count the votes
            conserver, supprimer, menfou, users = count_votes(votes["votes"])
            users = ", ".join(users)
            logger.info(
                f"Votes : {conserver} conserver, {supprimer} supprimer, {menfou} menfou"
            )
            embed_original.fields[
                4
            ].value = f"{conserver+supprimer+menfou} vote{'s' if conserver+supprimer+menfou>1 else ''} ({users})"
            # await ctx.message.edit(content=f"Voulez-vous conserver cette chanson dans playlist ?")
            # Update the message with the vote counts

            await ctx.message.edit(
                embeds=[
                    embed_original,
                    # await embed_message_vote(keep, remove, menfou),
                ]
            )

            # Send a message to the user informing them that their vote has been counted
            await ctx.send(
                f"Ton vote pour **{ctx.custom_id}** cette musique a bien été pris en compte ! 🗳️",
                ephemeral=True,
            )

    @interactions.Task.create(interactions.IntervalTrigger(minutes=1, seconds=0))
    async def check_playlist_changes(self):
        logger.debug("check_playlist_changes lancé")

        # Retrieve the channel where messages will be sent
        channel = await self.bot.fetch_channel(CHANNEL_ID)

        # Set the bot's status to "Online" with a custom activity
        await self.bot.change_presence(
            status=interactions.Status.ONLINE,
            activity=interactions.Activity(
                "Actualisation de la playlist", type=interactions.ActivityType.PLAYING
            ),
        )
        with open("data/snapshot.json", "r") as f:
            snapshot = json.load(f)
        old_snap = snapshot["snapshot"]
        duration = snapshot["duration"]
        length = snapshot["length"]

        # Compare the current snapshot ID to the previous snapshot ID
        new_snap = sp.playlist(PLAYLIST_ID, fields="snapshot_id")["snapshot_id"]
        if new_snap != old_snap:
            # Retrieve the tracks of the playlist
            try:
                results = sp.playlist_tracks(
                    playlist_id=PLAYLIST_ID, limit=100, offset=0
                )
            except spotipy.SpotifyException as e:
                logger.error(f"Spotify API Error : {str(e)}")
            tracks = results["items"]
            # get next 100 tracks
            while results["next"]:
                results = sp.next(results)
                tracks.extend(results["items"])

            # Process each track
            length = len(tracks)
            duration = 0
            # Compare the current track IDs to the previous track IDs
            last_track_ids = set(playlistItemsFull.distinct("_id"))
            current_track_ids = set({track["track"]["id"] for track in tracks})
            added_track_ids = current_track_ids - last_track_ids
            removed_track_ids = last_track_ids - current_track_ids
            for track in tracks:
                # Append the track to a list of tracks to be inserted into the MongoDB collection
                song = spotifymongoformat(track)
                # Retrieve the time the track was added and add its duration to the total duration of the playlist
                duration += track["track"]["duration_ms"]
                playlistItemsFull.update_one(
                    {"_id": track["track"]["id"]}, {"$set": song}, upsert=True
                )
            # Send messages for added or removed tracks
            if added_track_ids:
                logger.info(
                    f"{len(added_track_ids)} chanson(s) ont étées ajoutée(s) depuis la dernière vérification"
                )
                for track_id in added_track_ids:
                    song = playlistItemsFull.find_one({"_id": track_id})
                    track = sp.track(song["_id"], market="FR")
                    dt = interactions.utils.timestamp_converter(
                        datetime.fromisoformat(song["added_at"]).astimezone(
                            pytz.timezone("Europe/Paris")
                        )
                    )
                    embed = await embed_song(
                        song=song,
                        track=track,
                        type=Type.ADD,
                        time=dt,
                        person=discord2name.get(song["added_by"], song["added_by"]),
                    )
                    await channel.send(
                        content=f"{random.choice(startList)} <@{song['added_by']}>, {random.choice(finishList)}",
                        embeds=embed,
                    )
                    logger.info(
                        f"{track['name']} ajouté par {discord2name.get(song['added_by'], song['added_by'])}"
                    )

            if removed_track_ids:
                logger.info(
                    f"{len(removed_track_ids)} chanson(s) ont été supprimée(s) depuis la dernière vérification"
                )
                for track_id in removed_track_ids:
                    song = playlistItemsFull.find_one_and_delete({"_id": track_id})
                    track = sp.track(track_id, market="FR")
                    embed = await embed_song(
                        song=song,
                        track=track,
                        type=Type.DELETE,
                        time=interactions.Timestamp.utcnow(),
                    )
                    channel = await self.bot.fetch_channel(CHANNEL_ID)
                    await channel.send(embeds=embed)

            # Store the snapshot ID, length and duration in a JSON file
            with open("data/snapshot.json", "w") as f:
                json.dump(
                    {"snapshot": new_snap, "duration": duration, "length": length}, f
                )

            # Send a message indicating that the playlist has been updated
            message = f"Dernière màj de la playlist {interactions.Timestamp.utcnow().format(interactions.TimestampStyles.RelativeTime)}, si c'était il y a plus d'**une minute**, il y a probablement un problème\n`/addsong Titre et artiste de la chanson` pour ajouter une chanson\nIl y a actuellement **{length}** chansons dans la playlist, pour un total de **{milliseconds_to_string(duration)}**"
            message3 = requests.patch(
                url=PATCH_MESSAGE_URL,
                json={
                    "content": message,
                },
            )
            message3.raise_for_status()
        # Set the bot's status to "Idle"
        await self.bot.change_presence(status=interactions.Status.IDLE)

    @interactions.slash_command(
        name="rappel", description="Définit un rappel de vote", scopes=[GUILDE_GUILD_ID],
    )
    @interactions.slash_option(
        name="heure",
        description="Heure du rappel",
        opt_type=interactions.OptionType.INTEGER,
        required=True,
        choices=[
            interactions.SlashCommandChoice(name=str(i), value=i) for i in range(24)
        ],
    )
    @interactions.slash_option(
        "minute",
        "Minute du rappel",
        interactions.OptionType.INTEGER,
        required=True,
        choices=[
            interactions.SlashCommandChoice(name=str(5 * i), value=5 * i)
            for i in range(12)
        ],
    )
    async def setreminder(self, ctx: interactions.SlashContext, heure, minute):
        if ctx.channel_id == CHANNEL_ID:
            logger.info(f"{ctx.user.display_name} a ajouté un rappel à {heure}:{minute}")
            remind_time = datetime.strptime(f"{heure}:{minute}", "%H:%M")
            current_time = datetime.now()
            remind_time = current_time.replace(
                hour=remind_time.hour, minute=remind_time.minute, second=0, microsecond=0
            )
            if remind_time <= current_time:
                remind_time += timedelta(days=1)
            reminders[remind_time] = ctx.user.id  # Store the user ID in the dictionary
            await self.save_reminders()

            await ctx.send(f"Rappel défini à {remind_time.strftime('%H:%M')}.", ephemeral=True)
        else:
            await ctx.send("Cette commande n'est pas disponible dans ce salon.", ephemeral=True)
            logger.info(f"{ctx.user.display_name} a essayé d'utiliser la commande /rappel dans le salon #{ctx.channel.name} ({ctx.channel_id})")

    async def load_reminders(self):
        try:
            with open(REMINDERS_FILE, "r") as file:
                reminders_data = json.load(file)
                for remind_time_str, user_id in reminders_data.items():
                    remind_time = datetime.strptime(
                        remind_time_str, "%Y-%m-%d %H:%M:%S"
                    )
                    reminders[remind_time] = user_id
        except FileNotFoundError:
            pass
    async def load_voteinfos(self):
        with open("data/voteinfos.json", "r") as f:
            vote_infos.update(json.load(f))
    async def load_snapshot(self):
        with open("data/snapshot.json", "r") as f:
            snapshot.update(json.load(f))
    async def save_snapshot(self):
        with open("data/snapshot.json", "w") as f:
            json.dump(snapshot, f)
    async def save_voteinfos(self):
        with open("data/voteinfos.json", "w") as f:
            json.dump(vote_infos, f)

                
    async def save_reminders(self):
        reminders_data = {
            remind_time.strftime("%Y-%m-%d %H:%M:%S"): user_id
            for remind_time, user_id in reminders.items()
        }
        with open(REMINDERS_FILE, "w") as file:
            json.dump(reminders_data, file)

    @interactions.Task.create(interactions.IntervalTrigger(minutes=1))
    async def reminder_check(self):
        current_time = datetime.now()
        reminders_to_remove = []
        for remind_time, user_id in reminders.copy().items():
            if current_time >= remind_time:
                user = await self.bot.fetch_user(user_id)
                if user:
                    try:
                        votesDB.find_one({"_id": vote_infos["track_id"]})["votes"][str(user_id)]
                        logger.debug(f"{user.display_name} a déjà voté aujourd'hui !, pas de rappel envoyé")
                    except KeyError:
                        await user.send(f"Tu n'as pas voté aujourd'hui !")
                        logger.debug(f"Rappel envoyé à {user.display_name}")
                next_remind_time = remind_time + timedelta(days=1)
                reminders_to_remove.append(remind_time)
                reminders[next_remind_time] = user_id
        for remind_time in reminders_to_remove:
            del reminders[remind_time]

        await self.save_reminders()

    @interactions.slash_command(
        name="supprimerrappels",
        description="Supprime tous les rappels de vote",
        scopes=[GUILDE_GUILD_ID],
    )
    async def deletereminder(self, ctx: interactions.SlashContext):
        if ctx.channel_id == CHANNEL_ID:
            user_id = ctx.user.id
            reminders_to_remove = []
            for remind_time, reminder_user_id in reminders.items():
                if reminder_user_id == user_id:
                    reminders_to_remove.append(remind_time)

            for remind_time in reminders_to_remove:
                del reminders[remind_time]

            await self.save_reminders()
            await ctx.send("Tous les rappels ont été supprimés !", ephemeral=True)
        else:
            await ctx.send("Cette commande n'est pas disponible dans ce salon.", ephemeral=True)
            logger.info(f"Commande /supprimerrappels utilisée dans le salon #{ctx.channel.name} ({ctx.channel_id})")