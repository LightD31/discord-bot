import os
from datetime import datetime
from dict import spotify2id, spotify2name
from enum import Enum

import interactions
from dict import spotify2id


class Type(Enum):
    ADD = "add"
    DELETE = "delete"
    VOTE = "vote"
    VOTE_WIN = "vote_win"
    VOTE_LOSE = "vote_lose"


async def embed_song(
    song,
    type: Type,
    time,
    person=None,
    icon="https://upload.wikimedia.org/wikipedia/commons/thumb/1/19/Spotify_logo_without_text.svg/200px-Spotify_logo_without_text.svg.png",
):
    """
    Generates an embed message for a given song, with the specified type and timestamp.

    Args:
        song (dict): A dictionary containing information about the song.
        type (Type): The type of the message to generate (ADD, DELETE, VOTE, or VOTE_RESULT).
        time (datetime): The timestamp to display in the message.
        person (str, optional): The name of the person who added the song. Defaults to None.
        icon (str, optional): The URL of the icon to display in the message. Defaults to the Spotify logo.

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
        title = f"Vote ouvert jusqu'à {time}"
        color = interactions.MaterialColors.ORANGE
        footer = "Nettoyeur de playlist"
    elif type == Type.VOTE_WIN:
        title = f"Résultat du vote"
        color = interactions.MaterialColors.LIME
    elif type == Type.VOTE_LOSE:
        title = f"Résultat du vote"
        color = interactions.MaterialColors.DEEP_ORANGE
    else:
        raise ValueError("Invalid type")
    embed = interactions.Embed(title=title, color=color)
    embed.set_thumbnail(url=song["image_url"])
    embed.add_field(
        name="Titre",
        value=f"[{song['name']}]({song['song_url']})\n([Preview]({song['preview_url']}))",
        inline=True,
    )
    embed.add_field(name="Artiste", value=song["artists"], inline=True)

    embed.add_field(
        name="Album",
        value=f"[{song['album']}]({song['album_url']})",
        inline=True,
    )
    if type != Type.ADD:
        embed.add_field(
            name=" ",
            value=f"Initialement ajoutée par <@{person}> (ou pas)",
            inline=False,
        )
    if type == Type.ADD or type == Type.DELETE:
        embed.add_field(
            name=" ",
            value="[Ecouter la playlist](https://link.drndvs.fr/LaPlaylistDeLaGuilde)",
            inline=False,
        )
        embed.add_field(
            name=" ",
            value="[Ecouter les récents](https://link.drndvs.fr/LesDecouvertesDeLaGuilde)",
            inline=True,
        )
    embed.set_footer(
        text=footer,
        icon_url=icon,
    )
    embed.timestamp = time
    return embed


async def embed_message_vote(keep=0, remove=0, menfou=0):
    embed = interactions.Embed(color=interactions.MaterialColors.ORANGE)
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


def read_votes(votesfile):
    """Reads the votes from the votes file and returns a dictionary"""
    votes = {}
    if os.path.exists(votesfile):
        with open(votesfile, "r") as f:
            for line in f:
                user_id, vote = line.strip().split(":")
                votes[user_id] = vote
    return votes


def write_votes(votes, votesfile):
    """Writes the votes to the votes file"""
    with open(votesfile, "w") as f:
        for user_id, vote in votes.items():
            f.write(f"{user_id}:{vote}\n")


def count_votes(votes):
    """Counts the votes and returns a dictionary with the vote counts"""
    vote_counts = {}
    for vote in votes.values():
        if vote in vote_counts:
            vote_counts[vote] += 1
        else:
            vote_counts[vote] = 1
    return vote_counts


def spotifymongoformat(track, user=None):
    if user:
        song = {
            "_id": track["id"],
            "name": track["name"],
            "artists": ", ".join(artist["name"] for artist in track["artists"]),
            "album": track["album"]["name"],
            "added_by": user,
            "added_at": interactions.Timestamp.utcnow(),
            "image_url": track["album"]["images"][0]["url"],
            "preview_url": track["preview_url"],
            "duration_ms": track["duration_ms"],
            "song_url": track["external_urls"]["spotify"],
            "album_url": track["album"]["external_urls"]["spotify"],
        }
    else:
        song = {
            "_id": track["track"]["id"],
            "name": track["track"]["name"],
            "artists": ", ".join(
                artist["name"] for artist in track["track"]["artists"]
            ),
            "album": track["track"]["album"]["name"],
            "added_by": spotify2id.get(track["added_by"]["id"], "Inconnu"),
            "added_at": track["added_at"],
            "image_url": track["track"]["album"]["images"][0]["url"],
            "preview_url": track["track"]["preview_url"],
            "duration_ms": track["track"]["duration_ms"],
            "song_url": track["track"]["external_urls"]["spotify"],
            "album_url": track["track"]["album"]["external_urls"]["spotify"],
            "avatar_url": track["avatar_url"],
        }
    return song
