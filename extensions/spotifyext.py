import os
import random
from datetime import datetime

import interactions
import pytz
import requests
import spotipy
from dotenv import load_dotenv

from config import DEV_GUILD
from dict import finishList, spotify2id, spotify2name, startList
from src import logutil
from src.spotify import (
    embed_message_addremove,
    embed_message_vote,
    embed_message_vote_part1,
)
from src.utils import bot_presence, milliseconds_to_string

load_dotenv()

SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.environ.get("SPOTIFY_REDIRECT_URI")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
FOLDER_PATH = os.environ.get("FOLDER_PATH")
PLAYLIST_ID = os.environ.get("PLAYLIST_ID")
PATCH_MESSAGE_URL = os.environ.get("PATCH_MESSAGE_URL")
LOG_CHANNEL_ID = os.environ.get("LOG_CHANNEL_ID")

"Change this if you'd like - this labels log messages for debug mode"
logger = logutil.init_logger(os.path.basename(__file__))


def spotify_auth():
    # Create a SpotifyOAuth object to handle authentication
    sp_oauth = spotipy.SpotifyOAuth(
        client_id=os.environ.get("SPOTIFY_CLIENT_ID"),
        redirect_uri=os.environ.get("SPOTIFY_REDIRECT_URI"),
        client_secret=os.environ.get("SPOTIFY_CLIENT_SECRET"),
        scope="playlist-modify-private playlist-read-private",
        open_browser=False,
        cache_handler=spotipy.CacheFileHandler("./.cache"),
    )

    # Check if a valid token is already cached
    token_info = sp_oauth.get_cached_token()

    # If the token is invalid or doesn't exist, prompt the user to authenticate
    if (
        not token_info
        or sp_oauth.is_token_expired(token_info)
        or not sp_oauth.validate_token(token_info)
    ):
        if token_info:
            logger.warn("Cached token has expired or is invalid.")
        # Generate the authorization URL and prompt the user to visit it
        auth_url = sp_oauth.get_authorize_url()
        logger.warn(f"Please visit this URL to authorize the application: {auth_url}")
        print("Please visit this URL to authorize the application: {}".format(auth_url))

        # Wait for the user to input the response URL after authenticating
        auth_code = input("Enter the response URL: ")

        # Exchange the authorization code for an access token and refresh token
        token_info = sp_oauth.get_access_token(
            sp_oauth.parse_response_code(auth_code), as_dict=False
        )

    # Create a new instance of the Spotify API with the access token
    sp = spotipy.Spotify(auth_manager=sp_oauth, language="fr")

    return sp


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
        scopes=[DEV_GUILD] if DEV_GUILD else None,
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
        if str(ctx.channel_id) == CHANNEL_ID:
            with open("data/spotifylist.txt", "r") as f:
                track_ids = set(f.read().splitlines())
            logger.info(f"/addsong '{song}' utilisé par {ctx.author.username}")
            try:
                track = sp.track(song, market="FR")
            except spotipy.exceptions.SpotifyException:
                await ctx.send("Cette chanson n'existe pas.", ephemeral=True)
                logger.info("Commande /addsong utilisée avec une chanson inexistante")
            if track["id"] not in track_ids:
                # Récupération des résultats de la recherche
                sp.playlist_add_items(PLAYLIST_ID, [song])
                embed = await embed_message_addremove(
                    track,
                    person=ctx.author.username,
                    icon=ctx.author.avatar_url,
                )
                await ctx.send(
                    content=f"{random.choice(startList)} {ctx.author.mention}, {random.choice(finishList)}",
                    embeds=embed,
                )
                logger.info(f"{track['name']} ajouté par {ctx.author.username}")
                with open("data/spotifylist.txt", "a") as file:
                    file.write("\n" + track["id"])
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
                "Commande /addsong utilisée dans un mauvais salon("
                + ctx.channel.name
                + ")"
            )
        await bot_presence(self)

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
                        "name": (
                            item["artists"][0]["name"]
                            + " - "
                            + item["name"]
                            + " (Album : "
                            + item["album"]["name"]
                            + ")"
                        )[:100],
                        "value": item["uri"],
                    }
                    for item in items
                ]
        await ctx.send(choices=choices)

    @interactions.Task.create(interactions.TimeTrigger(hour=12, minute=52, utc=False))
    async def randomvote(self):
        logger.info("Tache randomvote lancée")
        with open("data/votesinfo.txt", "r") as f:
            message_id = f.readline().strip()
            track_id = f.readline().strip()
            logger.debug("message_id : " + message_id)
            logger.debug("track_id : " + track_id)
        channel = self.bot.get_channel(CHANNEL_ID)
        message = await channel.fetch_message(message_id)
        track = sp.track(track_id, market="FR")
        logger.debug("message : " + str(message.id))
        votes = {}
        with open("data/votes.txt", "r") as f:
            logger.debug("votes.txt ouvert")
            for line in f:
                user_id, vote = line.strip().split(":")
                if vote in votes:
                    votes[vote] += 1
                else:
                    votes[vote] = 1
        keep = votes.get("keep", 0)
        remove = votes.get("remove", 0)
        logger.debug("keep : " + str(keep))
        logger.debug("remove : " + str(remove))
        await message.unpin()
        if keep >= remove:
            await message.edit(
                content="La chanson a été conservée.",
                embeds=[
                    await embed_message_vote_part1(track, "Résultat du vote"),
                    await embed_message_vote(
                        keep=keep,
                        remove=remove,
                        title="Résultat du vote",
                    ),
                ],
                components=[],
            )
            logger.info("La chanson a été conservée.")
        else:
            await message.edit(
                content="La chanson a été supprimée.",
                embeds=[
                    await embed_message_vote_part1(track, "Résultat du vote"),
                    await embed_message_vote(
                        keep=keep,
                        remove=remove,
                        title="Résultat du vote",
                    ),
                ],
                components=[],
            )
            sp.playlist_remove_all_occurrences_of_items(PLAYLIST_ID, [track_id])
            logger.info("La chanson a été supprimée.")
            await Spotify.check_playlist_changes(self)
        with open("data/votes.txt", "w") as f:
            f.write("")
            logger.debug("votes.txt vidé")
        with open("data/spotifylist.txt", "r") as f:
            track_ids = set(f.read().splitlines())
            logger.debug("spotifylist.txt ouvert")
        with open("data/pollhistory.txt", "r") as f:
            poll_history = set(f.read().splitlines())
            logger.debug("pollhistory.txt ouvert")
        track_id = random.choice(list(track_ids))
        logger.debug("track_id choisie : " + track_id)
        while track_id in poll_history:
            logger.warning(
                "Chanson déjà votée, nouvelle chanson tirée au sort (" + track_id + ")"
            )
            track_id = random.choice(list(track_ids)).strip()
        track = sp.track(track_id, market="FR")
        logger.debug("track : " + str(track))
        channel = await self.bot.fetch_channel(CHANNEL_ID)
        message = await channel.send(
            content="Voulez-vous conserver cette chanson dans playlist ?",
            embeds=[
                await embed_message_vote_part1(
                    track,
                    "Vote ouvert jusqu'à "
                    + str(
                        interactions.utils.timestamp_converter(self.randomvote.next_run).format(interactions.TimestampStyles.RelativeTime)
                    ),
                ),
                await embed_message_vote(),
            ],
            components=[
                interactions.ActionRow(
                    interactions.Button(
                        label="Conserver",
                        style=interactions.ButtonStyle.SUCCESS,
                        emoji="✅",
                        custom_id="keep",
                    ),
                    interactions.Button(
                        label="Supprimer",
                        style=interactions.ButtonStyle.DANGER,
                        emoji="🗑️",
                        custom_id="remove",
                    ),
                )
            ],
        )
        await message.pin()
        await channel.purge(deletion_limit=1, after=message)
        with open("data/votesinfo.txt", "w") as file:
            file.write(str(message.id) + "\n" + str(track["id"]))
            logger.debug("votesinfo.txt écrit")
        with open("data/pollhistory.txt", "a") as file:
            file.write("\n" + track_id)
            logger.debug("pollhistory.txt écrit")
    @interactions.listen()
    async def on_component(self, event: interactions.api.events.Component):
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

    @interactions.Task.create(interactions.IntervalTrigger(minutes=1, seconds=0))
    async def check_playlist_changes(self):
        logger.debug("check_playlist_changes lancé")
        channel = await self.bot.fetch_channel(CHANNEL_ID)
        await self.bot.change_presence(
            status=interactions.Status.ONLINE,
            activity=interactions.Activity(
                "Actualisation de la playlist", type=interactions.ActivityType.PLAYING
            ),
        )
        new_snap = sp.playlist(PLAYLIST_ID, fields="snapshot_id")["snapshot_id"]
        with open("data/snapshot.txt", "r") as f:
            old_snap = f.readline().strip()
            duration = int(f.readline().strip())
            length = int(f.readline().strip())

        if new_snap != old_snap:
            last_track_ids = set()
            # Lecture des ID de pistes de la dernière vérification à partir d'un fichier local
            try:
                with open("data/spotifylist.txt", "r") as f:
                    last_track_ids = set(f.read().splitlines())
            except FileNotFoundError:
                logger.error("Playlist File not found")
                pass
            # Récupération des ID des pistes actuelles
            current_track_ids = set()
            try:
                results = sp.playlist_tracks(
                    playlist_id=PLAYLIST_ID, limit=100, offset=0
                )
            except spotipy.SpotifyException as e:
                logger.error("Spotify API Error : " + str(e))
            tracks = results["items"]
            # get next 100 tracks
            while results["next"]:
                results = sp.next(results)
                tracks.extend(results["items"])
            if tracks is not None:
                current_track_ids = {track["track"]["id"] for track in tracks}
            else:
                logger.error("No tracks found")
            track_dict_author = {}
            track_dict_time = {}
            length = len(tracks)
            duration = 0
            for track in tracks:
                track_dict_author[track["track"]["id"]] = track["added_by"]["id"]
                track_dict_time[track["track"]["id"]] = track["added_at"]
                duration += track["track"]["duration_ms"]
            # Comparaison avec les ID des pistes de la dernière vérification
            if last_track_ids:
                added_track_ids = current_track_ids - last_track_ids
                removed_track_ids = last_track_ids - current_track_ids
            else:
                added_track_ids = current_track_ids
                removed_track_ids = set()
            # Stockage des ID des pistes actuelles pour la prochaine vérification
            last_track_ids = current_track_ids.copy()

            if added_track_ids:
                # Envoi d'un message pour chaque nouvelle chanson ajoutée
                logger.info(
                    f"{len(added_track_ids)} chanson(s) ont étées ajoutée(s) depuis la dernière vérification"
                )
                for track_id in added_track_ids:
                    try:
                        track = sp.track(track_id, market="FR")
                    except ConnectionError:
                        logger.error("Error retrieving track")
                    try:
                        user = sp.user(track_dict_author[track_id])
                    except ConnectionError:
                        logger.error("Error retrieving user")
                        exit()

                    dt = interactions.utils.timestamp_converter(
                        datetime.fromisoformat(track_dict_time[track_id]).astimezone(
                            pytz.timezone("Europe/Paris")
                        )
                    )
                    embed = await embed_message_addremove(
                        track,
                        dt,
                        spotify2name.get(user["id"]),
                        user["images"][0]["url"],
                    )
                    await channel.send(
                        content=f"{random.choice(startList)} <@{spotify2id.get(user['id'], 'Unknown')}>, {random.choice(finishList)}",
                        embeds=embed,
                    )
                    logger.info(
                        f"{track['name']} ajouté par {spotify2name.get(user['id'], 'Unknown')}"
                    )
            if removed_track_ids:
                logger.info(
                    f"{len(removed_track_ids)} chanson(s) ont été supprimée(s) depuis la dernière vérification"
                )
                # Envoi d'un message pour chaque chanson supprimée
                for track_id in removed_track_ids:
                    track = sp.track(track_id, market="FR")
                    embed = await embed_message_addremove(
                        track,
                        delete=True,
                        time=interactions.Timestamp.utcnow(),
                    )
                    channel = await self.bot.fetch_channel(CHANNEL_ID)
                    await channel.send(embeds=embed)
                    # Mise à jour du fichier local avec les ID des pistes actuelles
            with open("data/spotifylist.txt", "w") as file:
                file.write("\n".join(current_track_ids))
            with open("data/snapshot.txt", "w") as f:
                f.write(str(new_snap) + "\n" + str(duration) + "\n" + str(length))
        await bot_presence(self)
        message3 = requests.patch(
            url=PATCH_MESSAGE_URL,
            json={
                "content": f"Dernière màj de la playlist {interactions.Timestamp.utcnow().format(interactions.TimestampStyles.RelativeTime)}, si c'était il y a plus d'**une minute**, il y a probablement un problème\n`/addsong Titre et artiste de la chanson` pour ajouter une chanson\nIl y a actuellement **{length}** chansons dans la playlist, pour un total de **{milliseconds_to_string(duration)}**",
            },
        )
        message3.raise_for_status()
