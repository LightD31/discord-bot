import interactions
import os
from dotenv import load_dotenv
from src import logutil

load_dotenv()

GUILD_ID_KUBZ = int(os.getenv("GUILD_ID_KUBZ"))

logger = logutil.init_logger(os.path.basename(__file__))

class Utils(interactions.Extension):

    @interactions.slash_command(
        name="delete",
        description="Supprimer des messages",
    )
    @interactions.slash_option("nombre", "Nombre de messages à supprimer", opt_type=interactions.OptionType.INTEGER, required=False)
    @interactions.slash_option("channel", "Channel dans lequel supprimer les messages", opt_type=interactions.OptionType.CHANNEL, required=False)
    @interactions.slash_default_member_permission(interactions.Permissions.ADMINISTRATOR)
    async def delete(self, ctx: interactions.SlashContext, nombre=1, channel=None):
        if channel is None:
            channel = ctx.channel
        await channel.purge(deletion_limit=nombre, reason=f"Suppression de {nombre} message(s) par {ctx.user.username} (ID: {ctx.user.id}) via la commande /delete")
        await ctx.send(
            f"{nombre} message(s) supprimé(s) dans le channel <#{channel.id}>",
            ephemeral=True,
        )
        logger.info(f"Suppression de {nombre} message(s) par {ctx.user.username} (ID: {ctx.user.id}) via la commande /delete")
    @interactions.slash_command(name="send" ,description="Envoyer un message dans un channel")
    @interactions.slash_option("message", "Message à envoyer", opt_type=interactions.OptionType.STRING, required=True)
    @interactions.slash_default_member_permission(interactions.Permissions.ADMINISTRATOR|interactions.Permissions.MANAGE_MESSAGES)
    async def send(self, ctx: interactions.SlashContext, message):
        sent = await ctx.channel.send(message)
        await ctx.send(f"Message envoyé\nid : {sent.id}\nchannel id : {sent.channel.id}", ephemeral=True)