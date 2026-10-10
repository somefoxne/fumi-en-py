"""
Cog managing utility tools and administrative commands.
Includes:
  /hi   – Greet Fumimi
  /calc – Evaluate math expressions safely using AST
  /say  – Send a message through Fumimi (requires Manage Messages permission)
  !sync – Prefix command to clear stale guild commands and resync slash commands
"""

import ast
import operator
import logging
import discord
from discord import app_commands
from discord.ext import commands

from embeds import error_embed

log = logging.getLogger("fumimi.cogs.utility")

# ── Safe math evaluator ────────────────────────────────────────────────────────
_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.FloorDiv: operator.floordiv,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def safe_eval(expr: str) -> float:
    """Safely evaluate mathematical expressions without using eval()."""
    tree = ast.parse(expr.strip(), mode="eval")

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError("Unsupported data type")
        if isinstance(node, ast.BinOp):
            op = _OPS.get(type(node.op))
            if op is None:
                raise ValueError("Unsupported operator")
            return op(_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            op = _OPS.get(type(node.op))
            if op is None:
                raise ValueError("Unsupported operator")
            return op(_eval(node.operand))
        raise ValueError("Invalid mathematical expression")

    return _eval(tree)


class UtilityCommands(commands.Cog, name="Utility"):
    def __init__(self, bot):
        self.bot = bot

    # ── /hi ───────────────────────────────────────────────────────────────────
    @app_commands.command(name="hi", description="Say hi to Fumimi!")
    async def cmd_hi(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            f"Hello {interaction.user.mention}! I'm Fumimi, the Danbooru bot for this server.\n"
            f"Use `/posts tags:...` to browse posts!"
        )

    # ── /calc ─────────────────────────────────────────────────────────────────
    @app_commands.command(name="calc", description="Calculate a mathematical expression")
    @app_commands.describe(expression="Math expression, e.g. 2**10 + 5*3")
    async def cmd_calc(self, interaction: discord.Interaction, expression: str):
        try:
            result = safe_eval(expression)
            if isinstance(result, float) and result.is_integer():
                result_str = f"{int(result):,}"
            else:
                result_str = f"{result:,.8g}"
            embed = discord.Embed(
                title="Calculator",
                description=f"`{expression}` = **{result_str}**",
                color=0x00AA00,
            )
            await interaction.response.send_message(embed=embed)
        except ZeroDivisionError:
            await interaction.response.send_message(
                embed=error_embed("Math Error", "Cannot divide by zero."), ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                embed=error_embed("Invalid Expression", f"`{expression}`\n{e}"), ephemeral=True
            )

    # ── /say ──────────────────────────────────────────────────────────────────
    @app_commands.command(name="say", description="Make Fumimi say a message (requires Manage Messages)")
    @app_commands.describe(message="The message to send")
    @app_commands.default_permissions(manage_messages=True)
    async def cmd_say(self, interaction: discord.Interaction, message: str):
        await interaction.response.send_message("Sent!", ephemeral=True)
        await interaction.channel.send(message)

    # ── !sync ─────────────────────────────────────────────────────────────────
    @commands.command(name="sync")
    async def cmd_manual_sync(self, ctx: commands.Context):
        """
        Administrative !sync command:
        Clears duplicate guild commands and resynchronizes global slash commands.
        """
        if not ctx.author.guild_permissions.administrator and not await self.bot.is_owner(ctx.author):
            await ctx.send("You need Administrator permissions to use this command.")
            return

        msg = await ctx.send("Clearing duplicate commands and resyncing slash commands...")
        try:
            # Clear guild-specific commands to eliminate duplicates
            if ctx.guild:
                self.bot.tree.clear_commands(guild=ctx.guild)
                await self.bot.tree.sync(guild=ctx.guild)

            # Synchronize global slash commands
            synced = await self.bot.tree.sync()

            await msg.edit(
                content=(
                    f"**Success!** Duplicate commands cleared.\n"
                    f"Currently synced **{len(synced)}** global commands.\n"
                    f"*(Press **Ctrl + R** in Discord if the command picker doesn't update immediately)*"
                )
            )
        except Exception as e:
            log.exception("Error syncing commands: %s", e)
            await msg.edit(content=f"Error syncing commands: {e}")


async def setup(bot):
    await bot.add_cog(UtilityCommands(bot))
