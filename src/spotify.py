import interactions
from datetime import datetime


async def embed_message_addremove(
    track,
    time=interactions.utils.timestamp_converter(datetime.now()),
    person="",
    icon="https://upload.wikimedia.org/wikipedia/commons/thumb/1/19/Spotify_logo_without_text.svg/200px-Spotify_logo_without_text.svg.png",
    delete=False,
):
    if delete:
        msg = "Chanson supprimée de la playlist"
        footer = ""
        color = interactions.MaterialColors.RED
    else:
        msg = "Chanson ajoutée à la playlist"
        footer = f"Ajoutée par {person}"
        color = interactions.Color.from_hex("1DB954")
    artistes = ", ".join(artist["name"] for artist in track["artists"])
    embed = interactions.Embed(title=msg, color=color)
    embed.set_thumbnail(url=track["album"]["images"][0]["url"])
    if track["preview_url"]:
        embed.add_field(
            name="Titre",
            value=f"[{track['name']}]({track['external_urls']['spotify']}) ([Preview]({track['preview_url']}))",
            inline=True,
        )
    else:
        embed.add_field(
            name="Titre",
            value=f"[{track['name']}]({track['external_urls']['spotify']})",
            inline=True,
        )
    embed.add_field(name="Artiste", value=artistes, inline=True)
    embed.add_field(
        name="Album",
        value=f"[{track['album']['name']}]({track['album']['external_urls']['spotify']})",
        inline=True,
    )
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


async def embed_message_vote(keep=0, remove=0, title="Vote déclenché"):
    embed = interactions.Embed(color=interactions.MaterialColors.ORANGE)
    embed.add_field(
        name="Conserver",
        value=f"{keep} vote(s)",
        inline=True,
    )
    embed.add_field(
        name="Supprimer",
        value=f"{remove} vote(s)",
        inline=True,
    )
    embed.set_footer(
        text="Nettoyeur de Playlist",
        icon_url="https://upload.wikimedia.org/wikipedia/commons/thumb/1/19/Spotify_logo_without_text.svg/200px-Spotify_logo_without_text.svg.png",
    )
    embed.timestamp = interactions.utils.timestamp_converter(datetime.now())
    return embed


async def embed_message_vote_part1(track, title):
    artistes = ", ".join(artist["name"] for artist in track["artists"])
    embed = interactions.Embed(title=title, color=interactions.MaterialColors.ORANGE)
    embed.set_thumbnail(url=track["album"]["images"][0]["url"])
    if track["preview_url"]:
        embed.add_field(
            name="Titre",
            value=f"[{track['name']}]({track['external_urls']['spotify']}) ([Preview]({track['preview_url']}))",
            inline=True,
        )
    else:
        embed.add_field(
            name="Titre",
            value=f"[{track['name']}]({track['external_urls']['spotify']})",
            inline=True,
        )
    embed.add_field(name="Artiste", value=artistes, inline=True)
    embed.add_field(
        name="Album",
        value=f"[{track['album']['name']}]({track['album']['external_urls']['spotify']})",
        inline=True,
    )
    return embed
