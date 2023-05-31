import interactions
import random
from dict import activityList
from datetime import datetime
from dotenv import load_dotenv
import os

load_dotenv()


def milliseconds_to_string(duration_ms):
    seconds = duration_ms / 1000
    days = seconds // 86400
    seconds %= 86400
    hours = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    seconds %= 60
    return f"{int(days)} jour(s) {int(hours):02d} heure(s) {int(minutes):02d} minute(s) et {int(seconds):02d} seconde(s)"


async def bot_presence(client):
    await client.bot.change_presence(
        status=interactions.Status.IDLE,
        activity=interactions.Activity(random.choice(activityList)),
    )
