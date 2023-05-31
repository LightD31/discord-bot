import interactions
import os
from dotenv import load_dotenv
from src import logutil

load_dotenv()

logger = logutil.init_logger(os.path.basename(__file__))


OWNER_ID = int(os.environ.get("OWNER_ID"))
class Utils(interactions.Extension):

    @interactions.slash_command(
        name="delete",
        description="Supprimer des messages",
    )
    @interactions.slash_option("nombre", "Nombre de messages à supprimer", opt_type=interactions.OptionType.INTEGER, required=False)
    @interactions.slash_option("channel", "Channel dans lequel supprimer les messages", opt_type=interactions.OptionType.CHANNEL, required=False)
    @interactions.slash_default_member_permission(interactions.Permissions.ADMINISTRATOR|interactions.Permissions.MANAGE_MESSAGES)
    async def delete(self, ctx: interactions.SlashContext, nombre=1, channel=None):
            if channel is None:
                channel = ctx.channel
            await channel.purge(deletion_limit=nombre, reason=f"Suppression de {nombre} message(s) par {ctx.user.username} (ID: {ctx.user.id}) via la commande /delete")
            await ctx.send(
                f"{nombre} message(s) supprimé(s) dans le channel <#{channel.id}>",
                ephemeral=True,
            )
            logger.info(f"Suppression de {nombre} message(s) par {ctx.user.username} (ID: {ctx.user.id}) via la commande /delete")