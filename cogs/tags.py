"""
Cog managing Tag and Wiki lookup commands on Danbooru.
Includes:
  /tag          – Look up tag metadata and wiki summary
  /related_tags – View related tags based on cosine similarity
  /related      – Shorthand alias for /related_tags
"""

import logging
import discord
from discord import app_commands
from discord.ext import commands

import settings
from danbooru_client import DanbooruError
from embeds import error_embed, tag_embed

log = logging.getLogger("fumimi.cogs.tags")


class TagCommands(commands.Cog, name="Tags"):
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

    # ── /tag ──────────────────────────────────────────────────────────────────
    @app_commands.command(name="tag", description="Look up tag info and wiki on Danbooru")
    @app_commands.describe(name="Tag name (use underscores, e.g. hatsune_miku)")
    async def cmd_tag(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer()
        tag_name = name.lower().strip().replace(" ", "_")
        try:
            tag = await self.bot.booru.get_tag(tag_name)
            if not tag:
                await interaction.followup.send(
                    embed=error_embed("Tag Not Found", f"Tag `{tag_name}` does not exist.")
                )
                return
            wiki = await self.bot.booru.get_wiki(tag_name)
            embed = tag_embed(tag, wiki, self.booru_url)
            await interaction.followup.send(embed=embed)
        except DanbooruError as e:
            await interaction.followup.send(embed=error_embed("API Error", e.message))
        except Exception as e:
            log.exception("Error in /tag name=%s", tag_name)
            await interaction.followup.send(embed=error_embed("Error", str(e)))

    @cmd_tag.autocomplete("name")
    async def autocomplete_tag_name(self, interaction: discord.Interaction, current: str):
        return await self.tag_autocomplete(interaction, current)

    # ── Related Tags Helper ───────────────────────────────────────────────────
    async def _handle_related_tags(self, interaction: discord.Interaction, tags: str, category: str = None):
        await interaction.response.defer()
        try:
            cat_param = None if (category is None or category == "all") else category
            data = await self.bot.booru.get_related_tags(tags, cat_param)
            related = data.get("related_tags", [])[:15]
            if not related:
                await interaction.followup.send(
                    embed=error_embed("No Results Found", f"No related tags found for query `{tags}`.")
                )
                return

            CAT_LABELS = {0: "General", 1: "Artist", 3: "Copyright", 4: "Character", 5: "Meta"}
            lines = []
            for rt in related:
                t = rt.get("tag", {})
                tname = t.get("name", "?")
                count = t.get("post_count", 0)
                cat   = t.get("category", 0)
                score = rt.get("cosine_similarity", 0)
                lines.append(f"`{tname}` — {count:,} posts | {CAT_LABELS.get(cat, '?')} | {score:.2f}")

            embed = discord.Embed(
                title=f"Related Tags: {tags}",
                url=f"{self.booru_url}/related_tag?query={tags}",
                description="\n".join(lines),
                color=0x9400D3,
            )
            if category and category != "all":
                embed.set_footer(text=f"Filtered by category: {category}")
            await interaction.followup.send(embed=embed)
        except DanbooruError as e:
            await interaction.followup.send(embed=error_embed("API Error", e.message))
        except Exception as e:
            log.exception("Error in /related_tags tags=%s", tags)
            await interaction.followup.send(embed=error_embed("Error", str(e)))

    # ── /related_tags ─────────────────────────────────────────────────────────
    @app_commands.command(name="related_tags", description="View list of related tags")
    @app_commands.describe(
        tags="Tag query to find relations for",
        category="Filter by tag category (optional, default: All)",
    )
    @app_commands.choices(category=[
        app_commands.Choice(name="All Categories", value="all"),
        app_commands.Choice(name="General",        value="general"),
        app_commands.Choice(name="Artist",         value="artist"),
        app_commands.Choice(name="Copyright",      value="copyright"),
        app_commands.Choice(name="Character",      value="character"),
        app_commands.Choice(name="Meta",           value="meta"),
    ])
    async def cmd_related_tags(
        self,
        interaction: discord.Interaction,
        tags: str,
        category: str = None,
    ):
        await self._handle_related_tags(interaction, tags, category)

    @cmd_related_tags.autocomplete("tags")
    async def autocomplete_related_tags(self, interaction: discord.Interaction, current: str):
        return await self.tag_autocomplete(interaction, current)

    # ── /related ──────────────────────────────────────────────────────────────
    @app_commands.command(name="related", description="View list of related tags (shorthand)")
    @app_commands.describe(
        tags="Tag query to find relations for",
        category="Filter by tag category (optional, default: All)",
    )
    @app_commands.choices(category=[
        app_commands.Choice(name="All Categories", value="all"),
        app_commands.Choice(name="General",        value="general"),
        app_commands.Choice(name="Artist",         value="artist"),
        app_commands.Choice(name="Copyright",      value="copyright"),
        app_commands.Choice(name="Character",      value="character"),
        app_commands.Choice(name="Meta",           value="meta"),
    ])
    async def cmd_related(
        self,
        interaction: discord.Interaction,
        tags: str,
        category: str = None,
    ):
        await self._handle_related_tags(interaction, tags, category)

    @cmd_related.autocomplete("tags")
    async def autocomplete_related(self, interaction: discord.Interaction, current: str):
        return await self.tag_autocomplete(interaction, current)


async def setup(bot):
    await bot.add_cog(TagCommands(bot))
