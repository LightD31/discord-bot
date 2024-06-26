import json
import os
import random

from interactions import Extension, Client, BrandColors, PartialEmoji, Embed, OptionType, SlashContext, slash_command, slash_option, Message
from interactions.client.utils import get
from dotenv import load_dotenv

from dict import discord2name
from src import logutil
from src.utils import load_config

logger = logutil.init_logger(os.path.basename(__file__))
config, module_config, enabled_servers = load_config("moduleSecretSanta")
load_dotenv()

SECRET_SANTA_FILE = config["SecretSanta"]["secretSantaFile"]
SECRET_SANTA_KEY = config["SecretSanta"]["secretSantaKey"]


class SecretSanta(Extension):
    def __init__(self, bot: Client):
        self.bot = bot

    def create_embed(self, message: str):
        return Embed(
            title="Père Noël Secret",
            description=message,
            color=BrandColors.RED,
        )

    def read_json_file(self):
        try:
            with open(SECRET_SANTA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def write_json_file(self, data):
        with open(SECRET_SANTA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def get_secret_santa_data(self):
        file = self.read_json_file()
        return file.get(SECRET_SANTA_KEY, {})

    def update_secret_santa_data(self, guild_id, message_id=None):
        file = self.read_json_file()
        if SECRET_SANTA_KEY not in file:
            file[SECRET_SANTA_KEY] = {}
        if message_id is None:
            del file[SECRET_SANTA_KEY][str(guild_id)]
        else:
            file[SECRET_SANTA_KEY][str(guild_id)] = message_id
        self.write_json_file(file)

    async def fetch_message(self, ctx, message_id):
        message = await ctx.channel.fetch_message(message_id)
        if message is None:
            await ctx.send(
                embed=self.create_embed(
                    "Il n'y a pas de Père Noël Secret en cours !\n(Le message n'a pas été trouvé)"
                )
            )
            self.update_secret_santa_data(ctx.guild.id)
            return None
        return message

    # Create a group of commands
    @slash_command(
        name="secretsanta",
        description="Les commandes du Père Noël Secret",
        sub_cmd_name="create",
        sub_cmd_description="Crée un Père Noël Secret",
        scopes=enabled_servers,
    )
    @slash_option(
        name="infos",
        description="Informations sur le secret Santa (facultatif)",
        required=False,
        opt_type=OptionType.STRING,
    )
    # @interactions.slash_default_member_permission(
    #     interactions.Permissions.ADMINISTRATOR
    # )
    async def secret_santa(self, ctx: SlashContext, infos: str = None):
        # Check if the secret santa is already running
        secret_santa_data = self.get_secret_santa_data()
        if str(ctx.guild.id) in secret_santa_data:
            await ctx.send(
                "Le Père Noël Secret est déjà en cours ! :santa:", ephemeral=True
            )
            return
        embed = Embed(
            title="Père Noël Secret",
            description="Ho, ho, ho, ce n'est pas Michel mais le Père Noël qui vous écrit.\nSi vous souhaitez participer au Secret Santa de **{guildname}**, cliquez sur la réaction :santa: ci-dessous.\n{infos}Signé : *le Père Noël*\nPS : Vérifiez que vous avez vos DMs ouverts aux membres de ce serveur".format(
                guildname=ctx.guild.name,
                infos=(infos if infos is not None else "") + "\n\u200b",
            ),
            color=BrandColors.RED,
        )
        message = await ctx.channel.send(content="@everyone", embed=embed)
        await message.add_reaction(":santa:")
        # Save message id and guild id in json file
        self.update_secret_santa_data(ctx.guild.id, message.id)
        await ctx.send("Le Père Noël Secret a été créé ! :santa:", ephemeral=True)

    @secret_santa.subcommand(
        sub_cmd_name="draw",
        sub_cmd_description="Effectue le tirage au sort du Père Noël Secret",
    )
    async def secret_santa_draw(self, ctx: SlashContext):
        await ctx.defer()
        secret_santa_data = self.get_secret_santa_data()
        # Get message id from json file the corresponding guild
        if str(ctx.guild.id) not in secret_santa_data:
            await ctx.send(
                embed=self.create_embed(
                    "Il n'y a pas de Père Noël Secret en cours !\n(Serveur non trouvé)"
                ),
                ephemeral=True,
            )
            return

        message_id = secret_santa_data[str(ctx.guild.id)]
        # Get the message
        message = await self.fetch_message(ctx, message_id)
        if message is None:
            return
        # Get the users who reacted to the message with the santa emoji regardless of the reaction index
        reaction = get(
            message.reactions, emoji=PartialEmoji.from_str("🎅")
        )
        users = await reaction.users().flatten()
        # Remove the bot from the list
        users.remove(self.bot.user)
        # Cancel if there are not enough users
        if len(users) < 2:
            await ctx.send("Il n'y a pas assez de participants ! :cry:", ephemeral=True)
            return
        # Shuffle the list
        logger.info(
            "List of participants : %s", ", ".join([user.username for user in users])
        )
        random.shuffle(users)
        logger.info("Tirage au sort : %s", ", ".join([user.username for user in users]))
        # Send a private message to each user
        description = "Ho, ho, ho, c'est Mich... le Père Noël.\nCettte année, tu dois offrir un cadeau à {mention} ! A toi de voir s'il a été sage.\n\u200b\nSigné : *Le vrai Père Noël, évidemment :disguised_face:*"
        for i, user in enumerate(users):

            if i == len(users) - 1:
                embed = self.create_embed(description.format(mention=discord2name.get(users[0].id, users[0].mention)))
                await user.send(embed=embed)
            else:
                embed = self.create_embed(description.format(mention=discord2name.get(user.id, users[i + 1].mention)))
                await user.send(embed=embed)

        # Delete the info from the json file
        self.update_secret_santa_data(ctx.guild.id)

        # Sort users by ID not to spoil the surprise
        users.sort(key=lambda user: user.id)
        # Send a message to the channel
        embed = self.create_embed(
            f"Le tirage au sort a été effectué pour les {len(users)} participants ! :santa:\n({', '.join([user.mention for user in users])})\nAllez voir dans vos DMs !\n\nSigné : *le Père Noël*"
        )
        await message.edit(embed=embed)
        await ctx.send(embed=embed)

    @secret_santa.subcommand(
        sub_cmd_name="cancel",
        sub_cmd_description="Annule le Père Noël Secret",
    )
    async def secret_santa_cancel(self, ctx: SlashContext):

        # Get message id from json file the corresponding guild
        secret_santa_data = self.get_secret_santa_data()
        if str(ctx.guild.id) not in secret_santa_data:
            await ctx.send(
                embed=self.create_embed(
                    "Il n'y a pas de Père Noël Secret en cours !\n(Serveur non trouvé)"
                ),
                ephemeral=True,
            )
            return

        message_id = secret_santa_data[str(ctx.guild.id)]
        # Get the message
        message: Message = await self.fetch_message(ctx, message_id)
        if message is None:
            return
        # Modify the message
        await message.edit(
            embed=self.create_embed("Le Père Noël Secret a été annulé !")
        )
        # Remove the reactions
        await message.clear_reactions(PartialEmoji.from_str("🎅"))
        # Delete the info from the json file
        self.update_secret_santa_data(ctx.guild.id)
        await ctx.send(
            embed=self.create_embed("Le Père Noël Secret a été annulé !"),
            ephemeral=True,
        )
