import os

import interactions
from mcstatus import JavaServer
import requests
from dotenv import load_dotenv

from src import logutil

logger = logutil.init_logger(os.path.basename(__file__))
load_dotenv()

MINECRAFT_SERV_MESSAGE_URL = os.environ.get("MINECRAFT_SERV_MESSAGE_URL")
MINECRAFT_SERV_MESSAGE_URL_NEW = os.environ.get("MINECRAFT_SERV_MESSAGE_URL_NEW")
MINECRAFT_ADDRESS = os.environ.get("MINECRAFT_ADDRESS")


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
                if colocStatus.players.online == 1:
                    string = (
                        str(colocStatus.players.sample[0].name) + " est sur le serveur"
                    )
                    players = str(colocStatus.players.sample[0].name)
                else:
                    string = (
                        "Il y a "
                        + str(colocStatus.players.online)
                        + " joueurs sur le serveur ("
                        + ", ".join(
                            [player.name for player in colocStatus.players.sample]
                        )
                        + ")"
                    )
                    players = "\n".join(
                        [player.name for player in colocStatus.players.sample]
                    )
            else:
                string = "Il n'y a personne sur le serveur"
                players = ""
            content = f"Serveur {colocStatus.version.name}\nAdresse du serveur : `http://{MINECRAFT_ADDRESS}:25565`\nCarte : [Cliquez ici](http://{MINECRAFT_ADDRESS}:8124 'Dynmap')\n{string}\nLatence : {colocStatus.latency:.2f} ms\nDernière actualisation {interactions.Timestamp.utcnow().format(interactions.TimestampStyles.RelativeTime)}"
            embeds = {
                "description": f"Adresse : `http://{MINECRAFT_ADDRESS}:25565`\nCarte : [Cliquez ici](http://{MINECRAFT_ADDRESS}:8124 'Dynmap')",
                "fields": [
                    {
                        "name": "Latence",
                        "value": "{:.2f} ms".format(colocStatus.latency),
                        "inline": "true",
                    },
                    {
                        "name": "Joueurs",
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
        except ConnectionResetError as e:
            logger.error(e)
            content = f"Adresse du serveur : `http://{MINECRAFT_ADDRESS}:25565`\nLe serveur est **hors-ligne**\nDernière actualisation {interactions.Timestamp.utcnow().format(interactions.TimestampStyles.RelativeTime)}"
            embeds = {
                "description": "Adresse : `http://"+MINECRAFT_ADDRESS+":25565`",
                "title": "Serveur Hors-ligne",
                "footer": {"text": "Serveur Minecraft du believe"},
                "timestamp": interactions.Timestamp.utcnow().isoformat(),
                "color": 16733525,
            }
        message1 = requests.patch(
            url=MINECRAFT_SERV_MESSAGE_URL,
            json={"content": content},
            headers={"Content-Type": "application/json"},
        )
        message1.raise_for_status()
        message2 = requests.patch(
            url=MINECRAFT_SERV_MESSAGE_URL_NEW,
            json={"embeds": [embeds]},
            headers={"Content-Type": "application/json"},
        )
        message2.raise_for_status()
