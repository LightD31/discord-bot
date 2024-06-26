import json
import os
import pytz
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from aiohttp import ClientSession
from interactions import (
    ActionRow,
    BaseChannel,
    Embed,
    Button,
    ButtonStyle,
    Extension,
    IntervalTrigger,
    Message,
    OptionType,
    SlashContext,
    Task,
    TimeTrigger,
    User,
    Client,
    listen,
    slash_command,
    slash_option,
    TimestampStyles,
    OrTrigger,
)
from interactions.api.events import Component
from interactions.client.utils import timestamp_converter
from src import logutil
from src.utils import load_config, fetch

logger = logutil.init_logger(os.path.basename(__file__))

config, module_config, enabled_servers = load_config("moduleColoc")

# Server specific module
module_config = module_config[enabled_servers[0]]

# Keep track of reminders
reminders = {}


class ColocClass(Extension):
    def __init__(self, bot: Client):
        self.bot: Client = bot

    @listen()
    async def on_startup(self):
        self.journa.start()
        await self.load_reminders()
        self.check_reminders.start()
        self.get_page_data.start()
        # await self.get_page_data()

    @slash_command(name="fesse", description="Fesses", scopes=enabled_servers)
    async def fesse(self, ctx: SlashContext):
        await ctx.send(
            "https://media1.tenor.com/m/YIUbUoKi8ZcAAAAC/sesame-street-kermit-the-frog.gif"
        )

    @slash_command(
        name="massageducul",
        description="Massage du cul",
        scopes=enabled_servers,
    )
    async def massageducul(self, ctx: SlashContext):
        await ctx.send("https://media1.tenor.com/m/h6OvENNtJh0AAAAC/bebou.gif")

    @Task.create(TimeTrigger(22, utc=False))
    async def journa(self):
        channel: BaseChannel = await self.bot.fetch_channel(
            module_config["colocZuniversChannelId"]
        )
        paris_tz = pytz.timezone("Europe/Paris")
        message: Message = (await channel.history(limit=1).flatten())[0]
        logger.debug(
            "Checking if message %s was posted today (message timestamp: %s today: %s",
            message.id,
            message.created_at.astimezone(paris_tz).strftime("%Y-%m-%d %H:%M:%S %Z"),
            datetime.now(pytz.UTC)
            .astimezone(paris_tz)
            .strftime("%Y-%m-%d %H:%M:%S %Z"),
        )
        if (
            message.created_at.astimezone(paris_tz).date()
            == datetime.now(paris_tz).date()
        ):
            logger.info(
                "Channel already posted today, skipping (message date: %s today: %s)",
                message.created_at.astimezone(paris_tz).date(),
                datetime.now(paris_tz).date(),
            )
            return
        await channel.send(
            ":robot: <@&934560421912911882>, heureusement que les robots n'oublient pas ! :robot:"
        )

    # Zunivers API
    async def load_reminders(self):
        """
        Load reminders from a JSON file and populate the reminders dictionary.
        """
        try:
            with open(
                f"{config['misc']['dataFolder']}/journa.json", "r", encoding="utf-8"
            ) as file:
                reminders_data = json.load(file)
                for remind_time_str, user_ids in reminders_data.items():
                    remind_time = datetime.strptime(
                        remind_time_str, "%Y-%m-%d %H:%M:%S"
                    )
                    reminders[remind_time] = set(user_ids)
        except FileNotFoundError:
            pass

    async def save_reminders(self):
        reminders_data = {
            remind_time.strftime("%Y-%m-%d %H:%M:%S"): list(user_ids)
            for remind_time, user_ids in reminders.items()
        }
        with open(
            f"{config['misc']['dataFolder']}/journa.json", "w", encoding="utf-8"
        ) as file:
            json.dump(reminders_data, file, indent=4)

    # Set reminder to /journa
    @slash_command(
        name="journa",
        sub_cmd_name="set",
        description="Gère les rappels pour voter",
        sub_cmd_description="Ajoute un rappel pour /journa",
        scopes=enabled_servers,
    )
    @slash_option(
        name="heure",
        description="Heure du rappel",
        opt_type=OptionType.INTEGER,
        required=True,
        min_value=0,
        max_value=23,
    )
    @slash_option(
        "minute",
        "Minute du rappel",
        OptionType.INTEGER,
        required=True,
        min_value=0,
        max_value=59,
    )
    async def rappelvote_set(self, ctx: SlashContext, heure: int, minute: int):
        remind_time = datetime.strptime(f"{heure}:{minute}", "%H:%M")
        current_time = datetime.now()
        remind_time = current_time.replace(
            hour=remind_time.hour,
            minute=remind_time.minute,
            second=0,
            microsecond=0,
        )
        if remind_time <= current_time:
            remind_time += timedelta(days=1)
        if remind_time not in reminders:
            reminders[remind_time] = set()
        reminders[remind_time].add(ctx.user.id)
        await self.save_reminders()
        await ctx.send(
            f"Rappel défini à {remind_time.strftime('%H:%M')}.", ephemeral=True
        )
        logger.info("%s a a jouté un rappel à %s", ctx.user.username, remind_time)

    @rappelvote_set.subcommand(
        sub_cmd_name="remove",
        sub_cmd_description="Supprime un rappel pour /journa",
    )
    async def deletereminder(self, ctx: SlashContext):
        user_id = ctx.user.id
        # create the list of reminders for the user
        reminders_list = []
        for remind_time, user_ids in reminders.copy().items():
            if user_id in user_ids:
                reminders_list.append(remind_time)
        # Create a button for each reminder
        buttons = [
            Button(
                label=remind_time.strftime("%H:%M"),
                style=ButtonStyle.SECONDARY,
                custom_id=str(remind_time.timestamp()),
            )
            for remind_time in reminders_list
        ]
        # Send a message with the buttons
        message = await ctx.send(
            "Quel rappel veux-tu supprimer ?",
            components=[ActionRow(*buttons)],
            ephemeral=True,
        )
        try:
            # Wait for the user to click a button
            button_ctx: Component = await self.bot.wait_for_component(
                components=[
                    str(remind_time.timestamp()) for remind_time in reminders_list
                ],
                timeout=60,
            )
            # Remove the reminder from the reminders dictionary
            remind_time = datetime.fromtimestamp(float(button_ctx.ctx.custom_id))
            reminders[remind_time].remove(user_id)
            if not reminders[remind_time]:
                del reminders[remind_time]
            # Save the reminders to a JSON file
            await self.save_reminders()
            # Send a message to the user indicating that the reminder has been removed
            await button_ctx.ctx.edit_origin(
                content=f"Rappel à {remind_time.strftime('%H:%M')} supprimé.",
                components=[],
            )
            logger.info(
                "Rappel à %s supprimé pour %s",
                remind_time.strftime("%H:%M"),
                ctx.user.display_name,
            )
        except TimeoutError:
            await ctx.send(
                "Tu n'as pas sélectionné de rappel à supprimer.", ephemeral=True
            )
            await message.edit(content="Aucun rappel sélectionné.", components=[])

    @Task.create(IntervalTrigger(minutes=1))
    async def check_reminders(self):
        current_time = datetime.now()
        reminders_to_remove = []
        async with ClientSession() as session:
            for remind_time, user_ids in reminders.copy().items():
                if remind_time <= current_time:
                    for user_id in user_ids.copy():
                        user: User = await self.bot.fetch_user(user_id)
                        # Check if the user did /journa today
                        response = await fetch(
                            f"https://zunivers-api.zerator.com/public/loot/{user.username}",
                            "json",
                        )
                        for day in response["lootInfos"]:
                            if day["date"] == current_time.strftime("%Y-%m-%d"):
                                if day["count"] == 0:
                                    await user.send(
                                        "Tu n'as pas encore /journa aujourd'hui, n'oublie pas !\nhttps://discord.com/channels/138283154589876224/808432657838768168"
                                    )
                                    logger.info("Rappel envoyé à %s", user.display_name)
                                else:
                                    logger.info(
                                        "Pas de rappel pour %s, /journa déjà fait aujourd'hui.",
                                        user.display_name,
                                    )
                        next_remind_time = remind_time + timedelta(days=1)
                        if next_remind_time not in reminders:
                            reminders[next_remind_time] = set()
                        reminders[next_remind_time].add(user_id)
                        user_ids.remove(user_id)
                    if not user_ids:
                        reminders_to_remove.append(remind_time)
        for remind_time in reminders_to_remove:
            del reminders[remind_time]
        await self.save_reminders()

    @Task.create(
        OrTrigger(
            *[
                TimeTrigger(hour=i, minute=j, utc=False)
                for i in [18, 19, 20, 21, 22, 23, 0]
                for j in [0, 15, 30, 45]
            ]
        )
    )
    async def get_page_data(self):
        try:
            channel = await self.bot.fetch_channel(module_config["colocMdrChannelId"])
            message = await channel.fetch_message(module_config["colocMdrMessageId"])
        except Exception as e:
            logger.error(f"Failed to fetch channel or message: {e}")
            return
        matches = await self.get_upcoming_matches()
        if matches is None:
            return

        embed = Embed(
            title="Prochains matchs de Mandatory",
            description="Source: [Liquipedia](https://liquipedia.net/valorant/Mandatory)",
            color=0xE04747,
            timestamp=datetime.now(),
            thumbnail="https://liquipedia.net/commons/images/d/d7/Mandatory_2022_allmode.png",
        )
        for match in matches:
            if match["date"] < datetime.now():
                embed.add_field(
                    name=f"<:zrtON:962320783038890054> {match['team1']} ({match['team1_tag']}) {match['score']} {match['team2']} ({match['team2_tag']}) en {match['format']}<:zrtON:962320783038890054>",
                    value=f"{match['tournament']}",
                )
            elif match["date"] - datetime.now() < timedelta(days=2):
                embed.add_field(
                    name=f"{match['team1']} ({match['team1_tag']}) vs {match['team2']} ({match['team2_tag']}) en {match['format']}",
                    value=f"{timestamp_converter(match['date']).format(TimestampStyles.RelativeTime)}\n{match['tournament']}",
                )
            else:
                embed.add_field(
                    name=f"{match['team1']} ({match['team1_tag']}) vs {match['team2']} ({match['team2_tag']}) en {match['format']}",
                    value=f"{timestamp_converter(match['date']).format(TimestampStyles.LongDateTime)}\n{match['tournament']}",
                    inline=False,
                )

        first_heading, standing_str_current, standing_str_last_week, standings = await self.get_standings()
        if standings is None:
            return

        embedClassement = Embed(
            title=f"Classement de {first_heading}",
            description=f"Source: [Liquipedia](https://liquipedia.net/valorant/VCL/2024/France/Split_2/Regular_Season)",
            color=0xE04747,
            timestamp=datetime.now(),
        )
        embedClassement.add_field(name="Semaine en cours", value=standing_str_current)
        embedClassement.add_field(name="Semaine précédente", value=standing_str_last_week)

        try:
            await message.edit(content="", embeds=[embed, embedClassement])
        except Exception as e:
            logger.error(f"Failed to edit message: {e}")

    async def get_upcoming_matches(self):
        page_title = "Mandatory"
        base_url = f"https://liquipedia.net/valorant/{page_title}"
        html_content = await fetch(base_url)
        if not html_content:
            return None

        soup = BeautifulSoup(html_content, "html.parser")
        matches_infobox = soup.find("div", {"class": "fo-nttax-infobox panel"})
        if not matches_infobox:
            logger.error("Failed to find matches infobox.")
            return None

        upcoming_matches = matches_infobox.find_all(
            "table", {"class": "wikitable wikitable-striped infobox_matches_content"}
        )

        matches = []
        for table in upcoming_matches:
            try:
                team1_element = table.select_one(".team-left span")
                team1 = (
                    team1_element["data-highlightingclass"] if team1_element else None
                )
                team1_tag_element = table.select_one(".team-left .team-template-text a")
                team1_tag = (
                    team1_tag_element.text.strip() if team1_tag_element else None
                )

                score_element = table.find("td", class_="versus").find(
                    "div", style="line-height:1.1"
                )
                score = score_element.text.strip() if score_element else None

                team2_element = table.select_one(".team-right span")
                team2 = (
                    team2_element["data-highlightingclass"] if team2_element else None
                )
                team2_tag_element = table.select_one(
                    ".team-right .team-template-text a"
                )
                team2_tag = (
                    team2_tag_element.text.strip() if team2_tag_element else None
                )

                date_timestamp_element = table.find(
                    "span", {"class": "timer-object timer-object-countdown-only"}
                )
                date_timestamp = (
                    date_timestamp_element["data-timestamp"]
                    if date_timestamp_element
                    else None
                )
                date = (
                    datetime.fromtimestamp(int(date_timestamp))
                    if date_timestamp
                    else None
                )
                match_format_element = table.select_one("td.versus abbr")
                match_format = (
                    match_format_element.text.strip() if match_format_element else None
                )
                tournament_element = table.select_one(".tournament-text a")
                tournament = (
                    tournament_element.text.strip() if tournament_element else None
                )

                if team1 and team2:
                    matches.append(
                        {
                            "team1": team1,
                            "team1_tag": team1_tag,
                            "team2": team2,
                            "team2_tag": team2_tag,
                            "date": date,
                            "format": match_format,
                            "tournament": tournament,
                            "score": score,
                        }
                    )
            except Exception as e:
                logger.error(f"Error parsing match data: {e}")

        return matches

    async def get_standings(self):
        page_title = "VCL/2024/France/Split_2/Regular_Season"
        base_url = f"https://liquipedia.net/valorant/{page_title}"
        html_content = await fetch(base_url)
        if not html_content:
            return None

        soup = BeautifulSoup(html_content, "html.parser")
        first_heading = soup.select_one(".firstHeading").text if soup.select_one(".firstHeading") else "Standings"

        table = soup.select_one('table.wikitable.wikitable-bordered.grouptable[style="width:425px;margin:0px"]')
        if not table:
            logger.error("Failed to find standings table.")
            return None

        team_rows = soup.select("tr[data-toggle-area-content]")
        if not team_rows:
            logger.error("No team rows found.")
            return None

        values = [int(row["data-toggle-area-content"]) for row in team_rows]
        max_value = max(values)
        last_week_value = max_value - 1
        logger.debug(f"Max value: {max_value}, Last week value: {last_week_value}")

        standings = {}
        standing_str_current = "```ansi\n"
        standing_str_last_week = "```ansi\n"

        for value in [max_value, last_week_value]:
            team_rows = table.select(f"tr[data-toggle-area-content='{value}']")
            logger.debug(f"Processing standings for value: {value} with {len(team_rows)} teams.")
            
            for row in team_rows:
                try:
                    cells = row.find_all("td")
                    standing_tag = row.find("th", {"class": lambda x: x and "bg-" in x, "style": "width:16px"})
                    standing = standing_tag.text.strip().strip(".") if standing_tag else ""

                    if cells:
                        team_name = cells[0].find("span", class_="team-template-text").text.strip()
                        logger.debug(f"Team name: {team_name}")

                        overall_result = "0-0" if cells[1].text.strip() == "-" else cells[1].text.strip() or "0-0"
                        match_result = cells[2].text.strip() if cells[2].text.strip() else "0-0"
                        round_result = cells[3].text.strip() if cells[3].text.strip() else "0-0"
                        round_diff = cells[4].text.strip() if cells[4].text.strip() else "+0"

                        rank_change_up = cells[0].find("span", class_="group-table-rank-change-up")
                        rank_change_down = cells[0].find("span", class_="group-table-rank-change-down")

                        if rank_change_up:
                            evolution = f"\u001b[1;32m{rank_change_up.text.strip()}\u001b[0m"
                        elif rank_change_down:
                            evolution = f"\u001b[1;31m{rank_change_down.text.strip()}\u001b[0m"
                        else:
                            evolution = "\u001b[1;30m==\u001b[0m"

                        standings[team_name] = standings.get(team_name, {})
                        standings[team_name][f"standing_{value}"] = {
                            "standing": standing,
                            "overall_result": overall_result,
                            "match_result": match_result,
                            "round_result": round_result,
                            "round_diff": round_diff,
                            "evolution": evolution,
                        }
                        logger.debug(standings[team_name][f"standing_{value}"])

                        formatted_str = f"{standing:<1} {team_name:<14} ({overall_result:<3}) {evolution:<2} ({round_diff})\n"
                        if value == max_value:
                            standing_str_current += formatted_str
                        else:
                            standing_str_last_week += formatted_str
                except Exception as e:
                    logger.error(f"Error parsing standings data: {e}")

        standing_str_current += "```"
        standing_str_last_week += "```"

        return first_heading, standing_str_current, standing_str_last_week, standings
