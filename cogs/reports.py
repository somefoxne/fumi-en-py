"""
Cog managing analytics, reports, and count commands on Danbooru.
Includes:
  /top_uploaders – ASCII box-drawing table of top 25 uploaders
  /count         – Count total matching posts for a query
"""

import logging
import urllib.parse
import discord
from discord import app_commands
from discord.ext import commands

import settings
from danbooru_client import DanbooruError
from embeds import error_embed, render_top_uploaders_table

log = logging.getLogger("fumimi.cogs.reports")


class ReportCommands(commands.Cog, name="Reports"):
    def __init__(self, bot):
        self.bot = bot
        self.booru_url = settings.get_active_booru_url()

    # ── Tag Autocomplete ───────────────────────────────────────────────────────
    async def tag_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        if not current or len(current) < 2:
            return []
        try:
            results = await self.bot.booru.autocomplete_tags(current, limit=10)
            return [
                app_commands.Choice(
                    name=f"{r.get('value', '')} ({r.get('post_count', 0):,})",
                    value=r.get("value", ""),
                )
                for r in results
            ][:25]
        except Exception:
            return []

    # ── /count ────────────────────────────────────────────────────────────────
    @app_commands.command(name="count", description="Count posts matching tags")
    @app_commands.describe(tags="Tags to search for (optional)")
    async def cmd_count(self, interaction: discord.Interaction, tags: str = ""):
        await interaction.response.defer()
        try:
            count = await self.bot.booru.get_post_count(tags=tags)
            label = f"`{tags}`" if tags else "all posts"
            search_url = f"{self.booru_url}/posts?tags={tags}" if tags else f"{self.booru_url}/posts"

            if count is None:
                embed = discord.Embed(
                    title="Unable to Calculate Post Count",
                    description=(
                        f"⚠️ Danbooru timed out calculating the post count for {label}.\n\n"
                        f"**Reason:** Searches with negative tags (`-`) or wildcards (`*`) can be too expensive for the database to count.\n"
                        f"🔗 [Click here to view search results on Danbooru]({search_url})"
                    ),
                    color=0xFEE75C,
                )
                embed.set_footer(text=f"danbooru • {self.booru_url}")
                await interaction.followup.send(embed=embed)
                return

            embed = discord.Embed(
                title="Post Count",
                description=f"**[{count:,} posts]({search_url})** matching {label}",
                color=0x5865F2,
            )
            embed.set_footer(text=f"danbooru • {self.booru_url}")
            await interaction.followup.send(embed=embed)
        except DanbooruError as e:
            await interaction.followup.send(embed=error_embed("API Error", e.message))
        except Exception as e:
            log.exception("Error in /count tags=%s", tags)
            await interaction.followup.send(embed=error_embed("Error", str(e)))

    # ── /top_uploaders ────────────────────────────────────────────────────────
    @app_commands.command(name="top_uploaders", description="Show top uploaders for a tag search.")
    @app_commands.describe(
        tags="Tags to search for.",
        limit="Number of uploaders to show (default: 25).",
    )
    async def cmd_top_uploaders(
        self,
        interaction: discord.Interaction,
        tags: str = "",
        limit: app_commands.Range[int, 0, 25] = 25,
    ):
        await interaction.response.defer()
        try:
            clean_tags = tags.strip()
            api_limit = 25 if (limit == 0 or limit is None) else limit

            total_posts_raw = await self.bot.booru.get_post_count(tags=clean_tags)
            total_posts = total_posts_raw or 0
            report = await self.bot.booru.get_top_uploaders(tags=clean_tags, limit=api_limit)

            report_url = f"{self.booru_url}/reports/posts?search[group]=uploader&search[group_limit]=25"
            if clean_tags:
                report_url += f"&search[tags]={urllib.parse.quote(clean_tags)}"

            if not report:
                tag_desc = f"Report for tags: `{clean_tags}`.\n\n" if clean_tags else ""
                embed = discord.Embed(
                    title="Top Uploaders Report",
                    url=report_url,
                    description=f"{tag_desc}No posts under that search!",
                    color=0x206694,
                    timestamp=discord.utils.utcnow(),
                )
                await interaction.followup.send(embed=embed)
                return

            headers = ["Name", "Uploads", "%"]
            rows = []
            for row in report:
                uname = row.get("uploader", "Unknown")
                posts_cnt = row.get("posts", 0)
                pct_str = f"{(posts_cnt / total_posts * 100):.2f}" if total_posts > 0 else "N/A"
                rows.append([uname, f"{posts_cnt:,}", pct_str])

            table_str = render_top_uploaders_table(headers, rows)

            desc_parts = ["Results may be cached for 1 hour."]
            if clean_tags:
                desc_parts.append(f"Report for tags: `{clean_tags}`.")
            desc_parts.append(table_str)

            embed = discord.Embed(
                title="Top Uploaders Report",
                url=report_url,
                description="\n".join(desc_parts),
                color=0x206694,
                timestamp=discord.utils.utcnow(),
            )

            await interaction.followup.send(embed=embed)
        except DanbooruError as e:
            await interaction.followup.send(embed=error_embed("API Error", e.message))
        except Exception as e:
            log.exception("Error in /top_uploaders tags=%s", tags)
            await interaction.followup.send(embed=error_embed("Error", str(e)))

    # Autocomplete delegates
    @cmd_count.autocomplete("tags")
    @cmd_top_uploaders.autocomplete("tags")
    async def autocomplete_tags_delegate(self, interaction: discord.Interaction, current: str):
        return await self.tag_autocomplete(interaction, current)


async def setup(bot):
    await bot.add_cog(ReportCommands(bot))
