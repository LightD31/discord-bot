import json
import os
from io import BytesIO, StringIO

import interactions
import pandas as pd
import prettytable
import pysftp
import requests
from dotenv import load_dotenv
from mcstatus import JavaServer
from src.utils import ticks_to_hms, create_dynamic_image
import interactions

from src import logutil

logger = logutil.init_logger(os.path.basename(__file__))
load_dotenv()

MINECRAFT_SERV_MESSAGE_URL = os.environ.get("MINECRAFT_SERV_MESSAGE_URL")
MINECRAFT_SERV_MESSAGE_URL_NEW = os.environ.get("MINECRAFT_SERV_MESSAGE_URL_NEW")
MINECRAFT_ADDRESS = os.environ.get("MINECRAFT_ADDRESS")
CHANNEL_ID_KUBZ = int(os.environ.get("CHANNEL_ID_KUBZ"))
MESSAGE_ID_KUBZ = int(os.environ.get("MESSAGE_ID_KUBZ"))


class Minecraft(interactions.Extension):
    def __init__(self, client):
        self.client = client

    @interactions.listen()
    async def on_startup(self):
        self.status.start()

    serverColoc = JavaServer(MINECRAFT_ADDRESS, 25565)

    @interactions.Task.create(interactions.IntervalTrigger(seconds=30))
    async def status(self, serverColoc=serverColoc):
        logger.debug("Updating Minecraft server status")
        try:
            colocStatus = serverColoc.status()
            if colocStatus.players.online > 0:
                players = "\n".join(
                        [player.name for player in colocStatus.players.sample]
                    )
                joueurs = f"Joueur{'s' if colocStatus.players.online > 1 else ''} ({colocStatus.players.online}/{colocStatus.players.max})"
            else:
                players = "\u200b"
                joueurs = "\u200b"
            embed1 = {
                "description": f"Adresse : `http://{MINECRAFT_ADDRESS}:25565`\nCarte : [Cliquez ici](http://{MINECRAFT_ADDRESS}:8124 'Dynmap')\nStats : [Cliquez ici](http://{MINECRAFT_ADDRESS}:8124/stats/index.html 'Stats')",
                "fields": [
                    {
                        "name": "Latence",
                        "value": "{:.2f} ms".format(colocStatus.latency),
                        "inline": "true",
                    },
                    {
                        "name": joueurs,
                        "value": players,
                        "inline": "true",
                    },
                    {
                        "name": "Dernière actualisation",
                        "value": interactions.Timestamp.utcnow().format(
                            interactions.TimestampStyles.RelativeTime
                        ),
                    },
                ],
                "title": "Serveur " + str(colocStatus.version.name),
                "footer": {"text": "Serveur Minecraft du believe"},
                "timestamp": interactions.Timestamp.utcnow().isoformat(),
                "color": 5635925,
            }
            embed1 = interactions.Embed.from_dict(embed1)
            df = pd.DataFrame()
            cnopts = pysftp.CnOpts()
            cnopts.hostkeys = None
            with pysftp.Connection(
                "192.168.1.13",
                username="admin",
                password="IcVAdw2w!dhE^h9QXoAJ",
                port=2224,
                cnopts=cnopts,
            ) as sftp:
                usercache = BytesIO()
                sftp.getfo("usercache.json", usercache)
                usercache.seek(0)
                users = json.load(usercache)
                uuid_to_name_dict = {}
                for item in users:
                    uuid = item["uuid"]
                    name = item["name"]
                    uuid_to_name_dict[uuid] = name
                player_data_list = []
                with sftp.cd("world/stats/"):
                    files = sftp.listdir()
                    for file in files:
                        with BytesIO() as fileio:
                            sftp.getfo(file, fileio)
                            fileio.seek(0)
                            playerdata = json.load(fileio)
                            deaths = (
                                playerdata.get("stats", {})
                                .get("minecraft:custom", {})
                                .get("minecraft:deaths", 0)
                            )
                            playtime = (
                                playerdata.get("stats", {})
                                .get("minecraft:custom", {})
                                .get("minecraft:play_time", 0)
                            )
                            walked = (
                                playerdata.get("stats", {})
                                .get("minecraft:custom", {})
                                .get("minecraft:walk_one_cm", 0)
                            )
                            quartz = (
                                playerdata.get("stats", {})
                                .get("minecraft:mined", {})
                                .get("minecraft:nether_quartz_ore", 0)
                            )
                            creepers = (
                                playerdata.get("stats", {})
                                .get("minecraft:killed_by", {})
                                .get("minecraft:creeper", 0)
                            )
                            walked = walked / 100000
                            ratio = deaths / (playtime / 20 / 60 / 60)
                            playtime = ticks_to_hms(playtime)

                            player_data = {
                                "Joueur": uuid_to_name_dict[
                                    str(file).removesuffix(".json")
                                ],
                                "Morts": deaths,
                                "Temps de jeu": playtime,
                                "Morts/h": ratio,
                                "Marche (km)": walked,
                                "Quartz minés": quartz,
                                "Morts par Creeper": creepers,
                            }
                            player_data_list.append(player_data)

                df = pd.DataFrame(player_data_list)
                df = df.sort_values(by="Morts/h", ascending=False)

                output = StringIO()
                df.to_csv(output, float_format="%.3f", index=False)
                output.seek(0)

                table = prettytable.from_csv(output)
                # table.field_names = ["Joueur", "Morts", "Temps", "Morts/h", "Distance marchée"]
                table.align = "r"
                table.align["Joueur"] = "l"
                table.set_style(prettytable.SINGLE_BORDER)
                table.padding_width = 1
                image = interactions.File(create_dynamic_image(table.get_string())[1], "stats.png")
                embed2 = interactions.Embed(
                    title="Stats",
                    description=f"```{table.get_string()}```",
                    timestamp=interactions.Timestamp.utcnow().isoformat(),
                    color=16733525,
                )
                embed2 = interactions.Embed(images=("attachment://stats.png"))
        except ConnectionResetError as e:
            logger.error(e)
            embed1 = {
                "description": "Adresse : `http://" + MINECRAFT_ADDRESS + ":25565`",
                "title": "Serveur Hors-ligne",
                "footer": {"text": "Serveur Minecraft du believe"},
                "timestamp": interactions.Timestamp.utcnow().isoformat(),
                "color": "16733525",
            }
            embed2 = {}
        channel = await self.bot.fetch_channel(CHANNEL_ID_KUBZ)
        message = await channel.fetch_message(MESSAGE_ID_KUBZ)
        await message.edit(content="", embeds=[embed1, embed2], files=image)

