"""
Cog managing comments and forum topics on Danbooru.
Includes:
  /comment – View latest comments on a specific post
  /forum   – Search Danbooru forum topics
"""

import logging
import discord
from discord import app_commands
from discord.ext import commands

import settings
from danbooru_client import DanbooruError
from embeds import error_embed, truncate

log = logging.getLogger("fumimi.cogs.forum")


class ForumCommands(commands.Cog, name="Forum"):
    def __init__(self, bot):
        self.bot = bot
        self.booru_url = settings.get_active_booru_url()

    # ── /comment ──────────────────────────────────────────────────────────────
    @app_commands.command(name="comment", description="View recent comments on a Danbooru post")
    @app_commands.describe(post_id="ID of the post to view comments for")
    async def cmd_comment(self, interaction: discord.Interaction, post_id: int):
        await interaction.response.defer()
        try:
            comments = await self.bot.booru.get_comments(post_id=post_id, limit=5)
            if not comments:
                await interaction.followup.send(
                    embed=error_embed("No Comments", f"Post #{post_id} does not have any comments.")
                )
                return
            embed = discord.Embed(
                title=f"Comments – Post #{post_id}",
                url=f"{self.booru_url}/posts/{post_id}",
                color=0x5865F2,
            )
            for c in comments:
                creator = c.get("creator", {})
                author = creator.get("name", "Anonymous") if isinstance(creator, dict) else str(creator)
                body = truncate(c.get("body", "*(empty)*"), 300)
                score = c.get("score", 0)
                score_str = f" ({'+'if score>=0 else ''}{score})" if score != 0 else ""
                embed.add_field(
                    name=f"{author}{score_str}",
                    value=body,
                    inline=False,
                )
            embed.set_footer(text=f"danbooru • Post #{post_id}")
            await interaction.followup.send(embed=embed)
        except DanbooruError as e:
            await interaction.followup.send(embed=error_embed("API Error", e.message))
        except Exception as e:
            log.exception("Error in /comment post_id=%s", post_id)
            await interaction.followup.send(embed=error_embed("Error", str(e)))

    # ── /forum ────────────────────────────────────────────────────────────────
    @app_commands.command(name="forum", description="Search Danbooru forum topics")
    @app_commands.describe(query="Search keyword (optional)")
    async def cmd_forum(self, interaction: discord.Interaction, query: str = ""):
        await interaction.response.defer()
        try:
            topics = await self.bot.booru.get_forum_topics(query=query, limit=5)
            if not topics:
                await interaction.followup.send(
                    embed=error_embed("No Results Found", f"No forum topics found for `{query}`.")
                )
                return
            embed = discord.Embed(
                title=f"Forum Topics" + (f": {query}" if query else ""),
                url=f"{self.booru_url}/forum_topics",
                color=0xFF8C00,
            )
            for t in topics:
                title = t.get("title", "Untitled")
                topic_id = t.get("id")
                response_count = t.get("response_count", 0)
                url = f"{self.booru_url}/forum_topics/{topic_id}"
                embed.add_field(
                    name=f"#{topic_id} – {truncate(title, 50)}",
                    value=f"[View topic]({url}) • {response_count} replies",
                    inline=False,
                )
            embed.set_footer(text=f"danbooru • {self.booru_url}")
            await interaction.followup.send(embed=embed)
        except DanbooruError as e:
            await interaction.followup.send(embed=error_embed("API Error", e.message))
        except Exception as e:
            log.exception("Error in /forum query=%s", query)
            await interaction.followup.send(embed=error_embed("Error", str(e)))


async def setup(bot):
    await bot.add_cog(ForumCommands(bot))
