import os
from datetime import datetime
from dict import spotify2id, spotify2name
from enum import Enum
import spotipy
from src import logutil

import interactions
from dict import spotify2id

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


class Type(Enum):
    ADD = "add"
    DELETE = "delete"
    VOTE = "vote"
    VOTE_WIN = "vote_win"
    VOTE_LOSE = "vote_lose"


async def embed_song(
    song,
    track,
    type: Type,
    time,
    person=None,
    icon="https://upload.wikimedia.org/wikipedia/commons/thumb/1/19/Spotify_logo_without_text.svg/200px-Spotify_logo_without_text.svg.png",
):
    """
    Creates an embed message for a Discord bot that displays information about a song.

    Args:
        song (dict): A dictionary containing information about the song, including the person who added it.
        track (dict): A dictionary containing information about the track, including its name, artist, and album.
        type (Type): An enum value indicating the type of message to display.
        time (datetime): A datetime object indicating the time the message was created.
        person (str, optional): The person who added the song. Defaults to None.
        icon (str, optional): The URL of the icon to use in the footer. Defaults to the Spotify logo.

    Returns:
        interactions.Embed: An embed message containing information about the song.
    """
    if not person:
        person = song["added_by"]
    if type == Type.ADD:
        title = "Chanson ajoutée à la playlist"
        footer = f"Ajoutée par {person}"
        color = 0x1DB954
    elif type == Type.DELETE:
        title = f"Chanson supprimée de la playlist"
        footer = ""
        color = interactions.MaterialColors.RED
    elif type == Type.VOTE:
        title = f"Vote ouvert jusqu'à {str(interactions.utils.timestamp_converter(time).format(interactions.TimestampStyles.RelativeTime))}"
        color = interactions.MaterialColors.ORANGE
        footer = "Nettoyeur de playlist"
    elif type == Type.VOTE_WIN:
        title = f"Résultat du vote"
        color = interactions.MaterialColors.LIME
        footer = ""
    elif type == Type.VOTE_LOSE:
        title = f"Résultat du vote"
        color = interactions.MaterialColors.DEEP_ORANGE
        footer = ""
    else:
        raise ValueError("Invalid type")
    embed = interactions.Embed(title=title, color=color)
    embed.set_thumbnail(url=track["album"]["images"][0]["url"])
    embed.add_field(
        name="Titre",
        value=f"[{track['name']}]({track['external_urls']['spotify']})\n([Preview]({track['preview_url']}))",
        inline=True,
    )
    embed.add_field(
        name="Artiste",
        value=", ".join(artist["name"] for artist in track["artists"]),
        inline=True,
    )

    embed.add_field(
        name="Album",
        value=f"[{track['album']['name']}]({track['album']['external_urls']['spotify']})",
        inline=True,
    )
    if type != Type.ADD:
        embed.add_field(
            name="\u200b",
            value=f"Initialement ajoutée par <@{person}>{' (ou pas)' if person == '108967780224614400' else ''}",
            inline=False,
        )
    if type == Type.VOTE:
        embed.add_field(
            name="Votes",
            value=f"0 votes",
            inline=False,
        )
    if type == Type.ADD or type == Type.DELETE:
        embed.add_field(
            name="\u200b",
            value="[Ecouter la playlist](https://link.drndvs.fr/LaPlaylistDeLaGuilde)",
            inline=False,
        )
        embed.add_field(
            name="\u200b",
            value="[Ecouter les récents](https://link.drndvs.fr/LesDecouvertesDeLaGuilde)",
            inline=True,
        )
    embed.set_footer(
        text=footer,
        icon_url=icon,
    )
    embed.timestamp = time
    return embed


async def embed_message_vote(keep=0, remove=0, menfou=0, color=interactions.MaterialColors.ORANGE):
    embed = interactions.Embed(color=color)
    embed.add_field(
        name="Conserver",
        value=f"{keep} vote{'s' if keep > 1 else ''}",
        inline=True,
    )
    embed.add_field(
        name="Supprimer",
        value=f"{remove} vote{'s' if remove > 1 else ''}",
        inline=True,
    )
    embed.add_field(
        name="Menfou",
        value=f"{menfou} vote{'s' if menfou > 1 else ''}",
        inline=True,
    )
    embed.set_footer(
        text="Nettoyeur de Playlist",
        icon_url="https://upload.wikimedia.org/wikipedia/commons/thumb/1/19/Spotify_logo_without_text.svg/200px-Spotify_logo_without_text.svg.png",
    )
    embed.timestamp = interactions.utils.timestamp_converter(datetime.now())
    return embed


def count_votes(votes):
    """Counts the votes and returns a dictionary with the vote counts"""
    vote_counts = {}
    for vote in votes.values():
        if vote in vote_counts:
            vote_counts[vote] += 1
        else:
            vote_counts[vote] = 1
    return vote_counts


def spotifymongoformat(track, user: interactions.User = None):
    if user:
        song = {
            "_id": track["id"],
            "added_by": user.id,
            "added_at": interactions.Timestamp.utcnow(),
            "duration_ms": track["duration_ms"],
        }
    else:
        song = {
            "_id": track["track"]["id"],
            "added_by": spotify2id.get(
                track["added_by"]["id"], track["added_by"]["id"]
            ),
            "added_at": track["added_at"],
            "duration_ms": track["track"]["duration_ms"],
        }
    return song
