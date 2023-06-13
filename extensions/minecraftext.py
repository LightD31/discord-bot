import asyncio
import os
from io import BytesIO, StringIO

import asyncssh
import interactions
import pandas as pd
import prettytable
from dotenv import load_dotenv
from mcstatus import JavaServer

from src import logutil
from src.minecraft import get_player_stats, get_users
from src.utils import create_dynamic_image

logger = logutil.init_logger(os.path.basename(__file__))

load_dotenv()

MINECRAFT_SERV_MESSAGE_URL = os.environ.get("MINECRAFT_SERV_MESSAGE_URL")
MINECRAFT_SERV_MESSAGE_URL_NEW = os.environ.get("MINECRAFT_SERV_MESSAGE_URL_NEW")
MINECRAFT_ADDRESS = os.environ.get("MINECRAFT_ADDRESS")
CHANNEL_ID_KUBZ = int(os.environ.get("CHANNEL_ID_KUBZ"))
MESSAGE_ID_KUBZ = int(os.environ.get("MESSAGE_ID_KUBZ"))
SFTPS_PASSWORD = os.environ.get("SFTPS_PASSWORD")


class Minecraft(interactions.Extension):
    def __init__(self, client):
        self.client = client
        self.image_cache = {}

    @interactions.listen()
    async def on_startup(self):
        self.status.start()
        self.stats.start()
        await self.status()
        await self.stats()

    serverColoc = JavaServer(MINECRAFT_ADDRESS, 25565)

    @interactions.Task.create(interactions.IntervalTrigger(seconds=30))
    async def status(self, serverColoc=serverColoc):
        logger.debug("Updating Minecraft server status")
        channel = await self.bot.fetch_channel(CHANNEL_ID_KUBZ)
        message = await channel.fetch_message(MESSAGE_ID_KUBZ)
        embed2Timestamp = message.embeds[1].timestamp
        embed2 = interactions.Embed(
            title="Stats",
            description=f"Actualisé toutes les 5 minutes\nDernière actualisation : {embed2Timestamp.format(interactions.TimestampStyles.RelativeTime)}",
            images=("attachment://stats.png"),
            color=0x00AA00,
            timestamp=embed2Timestamp,
        )
        try:
            colocStatus = serverColoc.status()
            if colocStatus.players.online > 0:
                players = "\n".join(
                    sorted([player.name for player in colocStatus.players.sample], key=str.lower)
                )
                joueurs = f"Joueur{'s' if colocStatus.players.online > 1 else ''} ({colocStatus.players.online}/{colocStatus.players.max})"
            else:
                players = "\u200b"
                joueurs = "\u200b"

            embed1 = interactions.Embed()
            embed1.description = f"Adresse : `http://{MINECRAFT_ADDRESS}:25565`\nCarte : [Cliquez ici](http://{MINECRAFT_ADDRESS}:8124 'Dynmap')\nStats : [Cliquez ici](http://{MINECRAFT_ADDRESS}:8124/stats/index.html 'Stats')"
            embed1.add_fields(
                interactions.EmbedField(
                    "Latence", "{:.2f} ms".format(colocStatus.latency), True
                ),
                interactions.EmbedField(joueurs, players, True),
                interactions.EmbedField(
                    "Dernière actualisation (Toutes les 30 secondes)",
                    interactions.Timestamp.utcnow().format(
                        interactions.TimestampStyles.RelativeTime
                    ),
                ),
            )
            embed1.title = "Serveur " + str(colocStatus.version.name)
            embed1.set_footer("Serveur Minecraft du believe")
            embed1.timestamp = interactions.Timestamp.utcnow().isoformat()
            embed1.color = 0x00AA00
            await message.edit(content="", embeds=[embed1, embed2])

        except (ConnectionResetError, ConnectionRefusedError) as e:
            embed1 = interactions.Embed(
                title="Serveur Hors-ligne",
                description="Adresse : `http://" + MINECRAFT_ADDRESS + ":25565`",
                fields=[
                    {
                        "name": "Dernière actualisation",
                        "value": interactions.Timestamp.utcnow().format(
                            interactions.TimestampStyles.RelativeTime
                        ),
                    }
                ],
                color=0xAA0000,
                timestamp=interactions.Timestamp.utcnow().isoformat(),
            )
            await message.edit(content="", embeds=[embed1, embed2])

    @interactions.Task.create(interactions.IntervalTrigger(minutes=5))
    async def stats(self):
        logger.debug("Updating Minecraft server stats")
        channel = await self.bot.fetch_channel(CHANNEL_ID_KUBZ)
        message = await channel.fetch_message(MESSAGE_ID_KUBZ)
        embed1 = message.embeds[0]
        async with asyncssh.connect(
            host="192.168.1.13",
            port=2224,
            username="admin",
            password=SFTPS_PASSWORD,
            known_hosts=None,
        ) as conn:
            async with conn.start_sftp_client() as sftp:
                tasks = []
                tasks.append(get_users(sftp, "usercache.json"))
                files = await sftp.glob("world/stats/*json")
                for file in files:
                    logger.debug(f"Opening {file}")
                    tasks.append(get_player_stats(sftp, file))
                results = await asyncio.gather(*tasks)
        users_dict = results[0]
        uuid_to_name_dict = {item["uuid"]: item["name"] for item in users_dict}
        df = pd.DataFrame(results[1:])
        df["Joueur"] = df["Joueur"].map(uuid_to_name_dict)
        df["Temps de jeu"] = pd.to_timedelta(df["Temps de jeu"], unit="s").dt.round(
            "1s"
        )
        df.sort_values(by="Temps de jeu", ascending=False, inplace=True)

        output = StringIO()
        df.to_csv(output, index=False, float_format="%.2f")
        output.seek(0)

        table = prettytable.from_csv(output)
        table.align = "r"
        table.align["Joueur"] = "l"
        table.set_style(prettytable.SINGLE_BORDER)
        table.padding_width = 1

        embed2 = interactions.Embed(
            title="Stats",
            description=f"Actualisé toutes les 5 minutes\nDernière actualisation : {interactions.Timestamp.utcnow().format(interactions.TimestampStyles.RelativeTime)}",
            images=("attachment://stats.png"),
            color=0x00AA00,
            timestamp=interactions.Timestamp.utcnow().isoformat(),
        )

        if table.get_string() in self.image_cache:
            await message.edit(content="", embeds=[embed1, embed2])
            logger.debug("Image from cache")
        else:
            imageIO = BytesIO()
            image, imageIO = create_dynamic_image(table.get_string())
            self.image_cache = {}
            self.image_cache[table.get_string()] = (image, imageIO)
            image = interactions.File(
                create_dynamic_image(table.get_string())[1], "stats.png"
            )
            await message.edit(content="", embeds=[embed1, embed2], file=image)
