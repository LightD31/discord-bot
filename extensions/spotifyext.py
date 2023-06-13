import io
import os
import random
from datetime import datetime

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

votes_doc = "votes"
vote_infos_doc = "vote_infos"
pollhistory_doc = "pollhistory"
snapshot_doc = "snapshot"
track_ids_doc = "track_ids"

"Change this if you'd like - this labels log messages for debug mode"
logger = logutil.init_logger(os.path.basename(__file__))

client = pymongo.MongoClient(MONGO_SERV)
db = client["Playlist"]
playlistItemsFull = db["playlistItemsFull"]


sp = spotify_auth()


class Spotify(interactions.Extension):
    def __init__(self, bot: interactions.client):
        self.bot = bot

    @interactions.listen()
    async def on_startup(self):
        self.check_playlist_changes.start()
        self.randomvote.start()

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
        """Register as an extension command"""
        await self.bot.change_presence(status=interactions.Status.ONLINE)
        if ctx.channel_id == CHANNEL_ID:
            last_track_ids = set(
                playlistItemsFull.find_one({"_id": track_ids_doc})["track_ids"]
            )
            logger.info(f"/addsong '{song}' utilisé par {ctx.author.username}")
            try:
                track = sp.track(song, market="FR")
                song = spotifymongoformat(track, ctx.author)
            except spotipy.exceptions.SpotifyException:
                await ctx.send("Cette chanson n'existe pas.", ephemeral=True)
                logger.info("Commande /addsong utilisée avec une chanson inexistante")
            if song["_id"] not in last_track_ids:
                playlistItemsFull.insert_one(song)
                # Récupération des résultats de la recherche
                sp.playlist_add_items(PLAYLIST_ID, [song["_id"]])
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
                logger.info(f"{track['name']} ajouté par {ctx.author.username}")
                playlistItemsFull.update_one(
                    {"_id": track_ids_doc}, {"$push": {"track_ids": song["_id"]}}
                )
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
        if not ctx.input_text:
            choices = [
                {
                    "name": "Veuillez entrer un nom de chanson",
                    "value": "error",
                }
            ]
        else:
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

    @interactions.Task.create(interactions.TimeTrigger(hour=13, minute=00, utc=False))
    async def randomvote(self):
        logger.info("Tache randomvote lancée")
        vote_info = playlistItemsFull.find_one(
            {"_id": vote_infos_doc}, {"message_id": 1, "track_id": 1}
        )
        message_id = vote_info["message_id"]
        track_id = vote_info["track_id"]
        logger.debug(f"message_id: {message_id}")
        logger.debug(f"track_id: {track_id}")
        channel = self.bot.get_channel(CHANNEL_ID)
        message = await channel.fetch_message(message_id)
        logger.debug(f"message : {str(message.id)}")
        votes = playlistItemsFull.find_one(
            {"_id": votes_doc, track_id: {"$exists": True}}, {track_id: 1}
        ).get(track_id, {})
        vote_counts = count_votes(votes)
        conserver = vote_counts.get("conserver", 0)
        supprimer = vote_counts.get("supprimer", 0)
        logger.debug(f"keep : {str(conserver)}")
        logger.debug(f"remove : {str(supprimer)}")
        song = playlistItemsFull.find_one({"_id": track_id})
        track = sp.track(song["_id"], market="FR")
        await message.unpin()
        if conserver >= supprimer:
            await message.edit(
                content="La chanson a été conservée.",
                embeds=[
                    await embed_song(
                        song=song,
                        track=track,
                        type=Type.VOTE_WIN,
                        time=interactions.Timestamp.utcnow(),
                    ),
                    await embed_message_vote(keep=conserver, remove=supprimer),
                ],
                components=[],
            )
            logger.info("La chanson a été conservée.")
        else:
            await message.edit(
                content="La chanson a été supprimée.",
                embeds=[
                    await embed_song(
                        song, Type.VOTE_LOSE, interactions.Timestamp.now()
                    ),
                    await embed_message_vote(
                        keep=conserver,
                        remove=supprimer,
                    ),
                ],
                components=[],
            )
            sp.playlist_remove_all_occurrences_of_items(PLAYLIST_ID, [track_id])
            playlistItemsFull.delete_one({"_id": track_id})
            logger.info("La chanson a été supprimée.")
            await Spotify.check_playlist_changes()
        track_ids = set(playlistItemsFull.find_one({"_id": track_ids_doc})["track_ids"])
        pollhistory = set(
            playlistItemsFull.find_one({"_id": pollhistory_doc})["pollhistory"]
        )
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
            content="Voulez-vous conserver cette chanson dans playlist ?",
            embeds=[
                await embed_song(
                    song=song,
                    track=track,
                    type=Type.VOTE,
                    time=str(self.randomvote.next_run),
                ),
                await embed_message_vote(),
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
        playlistItemsFull.update_one(
            {"_id": vote_infos_doc},
            {"$set": {"message_id": str(message.id), "track_id": track_id}},
        )
        playlistItemsFull.update_one(
            {"_id": pollhistory_doc}, {"$push": {"pollhistory": track_id}}
        )

    @interactions.listen()
    async def on_component(self, event: interactions.api.events.Component):
        """Called when a component is clicked"""
        ctx = event.ctx
        vote_infos = playlistItemsFull.find_one(
            {"_id": vote_infos_doc}, {"message_id": 1, "track_id": 1}
        )
        message_id = vote_infos.get("message_id")
        track_id = vote_infos.get("track_id")
        if ctx.message.id == int(message_id):
            embed_original = ctx.message.embeds[0]
            # Check if the user has already voted and update their vote if necessary
            user_id = str(ctx.user.id)
            votes = playlistItemsFull.find_one_and_update(
                {"_id": votes_doc},
                {"$set": {f"{track_id}.{user_id}": ctx.custom_id}},
                upsert=True,
                return_document=pymongo.ReturnDocument.AFTER,
            )
            logger.info(f"User {ctx.user.username} voted {ctx.custom_id}")
            # Count the votes
            vote_counts = count_votes(votes.get(track_id, {}))
            keep = vote_counts.get("conserver", 0)
            remove = vote_counts.get("supprimer", 0)
            menfou = vote_counts.get("menfou", 0)

            # Update the message with the vote counts
            await ctx.message.edit(
                embeds=[
                    embed_original,
                    await embed_message_vote(keep, remove, menfou),
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

        # Retrieve the current snapshot ID of the playlist
        snapshot = playlistItemsFull.find_one({"_id": snapshot_doc})
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
            last_track_ids = set(
                playlistItemsFull.find_one({"_id": track_ids_doc})["track_ids"]
            )
            current_track_ids = {track["track"]["id"] for track in tracks}
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
                    track = sp.track(song["_id"], market="FR")
                    embed = await embed_song(
                        song=song,
                        track=track,
                        type=Type.DELETE,
                        time=interactions.Timestamp.utcnow(),
                    )
                    channel = await self.bot.fetch_channel(CHANNEL_ID)
                    await channel.send(embeds=embed)

            # Update the list of track IDs for the next check
            playlistItemsFull.update_one(
                {"_id": track_ids_doc}, {"$set": {"track_ids": list(current_track_ids)}}
            )

            # Update the snapshot ID and playlist information in the MongoDB collection
            playlistItemsFull.update_one(
                {"_id": snapshot_doc},
                {
                    "$set": {
                        "snapshot": new_snap,
                        "duration": duration,
                        "length": length,
                    }
                },
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
        name="initplaylist", description="Initialise la playlist", scopes=[DEV_GUILD]
    )
    @interactions.slash_option(
        "playlist",
        "Playlist à initialiser",
        interactions.OptionType.STRING,
        required=False,
    )
    async def initplaylist(self, ctx: interactions.SlashContext, playlist=PLAYLIST_ID):
        await ctx.defer()
        results = sp.playlist_tracks(playlist_id=playlist, limit=100, offset=0)
        tracks = results["items"]
        while results["next"]:
            results = sp.next(results)
            tracks.extend(results["items"])
        cache = {}
        # Insert tracks into MongoDB collection
        mongotracks = []
        track_ids = []
        for track in tracks:
            mongotracks.append(spotifymongoformat(track))
            track_ids.append(track["track"]["id"])  # Append track ID to list
        playlistItemsFull.insert_many(mongotracks)
        playlistItemsFull.update_one(
            {"_id": track_ids_doc}, {"$set": {"track_ids": track_ids}}, upsert=True
        )
        with open("data/pollhistory.txt", "r") as f:
            pollhistory = set(f.read().splitlines())
            playlistItemsFull.update_one(
                {"_id": pollhistory_doc},
                {"$set": {"pollhistory": list(pollhistory)}},
                upsert=True,
            )
        with open("data/votesinfo.txt", "r") as f:
            message_id = f.readline().strip()
            track_id = f.readline().strip()
            playlistItemsFull.update_one(
                {"_id": vote_infos_doc},
                {"$set": {"message_id": message_id, "track_id": track_id}},
                upsert=True,
            )
        with open("data/votes.txt", "r") as f:
            votes = {}
            if os.path.exists("data/votes.txt"):
                with open("data/votes.txt", "r") as f:
                    for line in f:
                        user_id, vote = line.strip().split(":")
                        votes[user_id] = vote
                        playlistItemsFull.update_one(
                            {"_id": votes_doc},
                            {"$set": {f"{track_id}.{user_id}": vote}},
                            upsert=True,
                        )
        with open("data/snapshot.txt", "r") as f:
            snapshot = f.readline().strip()
            duration = int(f.readline().strip())
            length = int(f.readline().strip())
            playlistItemsFull.update_one(
                {"_id": snapshot_doc},
                {
                    "$set": {
                        "snapshot": snapshot,
                        "duration": duration,
                        "length": length,
                    }
                },
                upsert=True,
            )
        await ctx.send("Playlist initialisée")
