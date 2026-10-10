"""
Cog managing post search and browsing commands for Danbooru.
Includes:
  /post      – View a Danbooru post by ID
  /posts     – Search posts by tags
  /random    – Fetch a random post
  /popular   – Browse popular posts by day / week / month
  on_message – Auto-embed Danbooru post URLs shared in chat
"""

import re
import logging
import discord
from discord import app_commands
from discord.ext import commands

import settings
from danbooru_client import DanbooruError
from embeds import (
    error_embed,
    prepare_post_display,
    PostView,
    MultiPostView,
)

log = logging.getLogger("fumimi.cogs.posts")


class PostCommands(commands.Cog, name="Posts"):
    def __init__(self, bot):
        self.bot = bot
        self.booru_url = settings.get_active_booru_url()
        self.post_url_re = self._build_post_url_re()

    def _build_post_url_re(self) -> re.Pattern:
        domains = "|".join(re.escape(d) for d in settings.BOORU_DOMAINS)
        return re.compile(
            rf"https?://(?:{domains})/posts/(\d+)",
            re.IGNORECASE,
        )

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

    # ── /post ─────────────────────────────────────────────────────────────────
    @app_commands.command(name="post", description="View a Danbooru post by ID")
    @app_commands.describe(post_id="ID of the post to view")
    async def cmd_post(self, interaction: discord.Interaction, post_id: int):
        await interaction.response.defer()
        try:
            post = await self.bot.booru.get_post(post_id)
            session = await self.bot.booru._get_session()
            embed, file = await prepare_post_display(post, interaction.channel, self.booru_url, session)
            view = PostView(post, self.booru_url)
            if file:
                await interaction.followup.send(embed=embed, file=file, view=view)
            else:
                await interaction.followup.send(embed=embed, view=view)
        except DanbooruError as e:
            await interaction.followup.send(embed=error_embed("Post Not Found", e.message))
        except discord.errors.HTTPException as e:
            if e.code == 20009:
                await interaction.followup.send(
                    content="**Age-Restricted Content:** Discord blocked sending this media in a regular channel. Please enable **Age-Restricted (18+)** for this channel or use the Download button below!",
                    view=view if "view" in locals() else discord.utils.MISSING,
                )
            else:
                await interaction.followup.send(embed=error_embed("Discord Error", str(e)))
        except Exception as e:
            log.exception("Error fetching post %s", post_id)
            await interaction.followup.send(embed=error_embed("Error", str(e)))

    # ── /posts ────────────────────────────────────────────────────────────────
    @app_commands.command(name="posts", description="Search Danbooru posts by tags")
    @app_commands.describe(
        tags="Tags to search for (space-separated, e.g. hatsune_miku solo)",
        limit="Number of results (1–4, default: 3)",
        page="Page number (default: 1)",
    )
    async def cmd_posts(
        self,
        interaction: discord.Interaction,
        tags: str = "",
        limit: app_commands.Range[int, 1, 4] = 3,
        page: app_commands.Range[int, 1, 1000] = 1,
    ):
        await interaction.response.defer()
        try:
            posts = await self.bot.booru.get_posts(tags=tags, limit=limit, page=page)
            if not posts:
                await interaction.followup.send(
                    embed=error_embed("No Results Found", f"No posts found for query `{tags or '(all)'}`.")
                )
                return
            session = await self.bot.booru._get_session()
            embeds = []
            files = []
            for p in posts:
                emb, f = await prepare_post_display(p, interaction.channel, self.booru_url, session)
                embeds.append(emb)
                if f:
                    files.append(f)
            view = MultiPostView(posts, self.booru_url) if len(posts) > 1 else PostView(posts[0], self.booru_url)
            label = f"`{tags}`" if tags else "*(all)*"
            send_kwargs = {
                "content": f"Found {len(posts)} result(s) for {label} (page {page}):",
                "embeds": embeds,
                "view": view,
            }
            if files:
                send_kwargs["files"] = files
            await interaction.followup.send(**send_kwargs)
        except DanbooruError as e:
            await interaction.followup.send(embed=error_embed("API Error", e.message))
        except discord.errors.HTTPException as e:
            if e.code == 20009:
                await interaction.followup.send(
                    content="**Age-Restricted Content:** Discord blocked displaying this media in a regular channel. Please use an age-restricted channel or click the Download buttons below!",
                    view=view if "view" in locals() else discord.utils.MISSING,
                )
            else:
                await interaction.followup.send(embed=error_embed("Discord Error", str(e)))
        except Exception as e:
            log.exception("Error in /posts tags=%s", tags)
            await interaction.followup.send(embed=error_embed("Error", str(e)))

    @cmd_posts.autocomplete("tags")
    async def autocomplete_posts_tags(self, interaction: discord.Interaction, current: str):
        return await self.tag_autocomplete(interaction, current)

    # ── /random ───────────────────────────────────────────────────────────────
    @app_commands.command(name="random", description="Fetch a random post from Danbooru")
    @app_commands.describe(tags="Filter tags (optional)")
    async def cmd_random(self, interaction: discord.Interaction, tags: str = ""):
        await interaction.response.defer()
        try:
            post = await self.bot.booru.get_random_post(tags=tags)
            session = await self.bot.booru._get_session()
            embed, file = await prepare_post_display(post, interaction.channel, self.booru_url, session)
            view = PostView(post, self.booru_url)
            label = f" for tags `{tags}`" if tags else ""
            if file:
                await interaction.followup.send(
                    content=f"Random post{label}:",
                    embed=embed,
                    file=file,
                    view=view,
                )
            else:
                await interaction.followup.send(
                    content=f"Random post{label}:",
                    embed=embed,
                    view=view,
                )
        except DanbooruError as e:
            await interaction.followup.send(embed=error_embed("Error", e.message))
        except discord.errors.HTTPException as e:
            if e.code == 20009:
                await interaction.followup.send(
                    content="**Age-Restricted Content:** Discord blocked sending this media in a regular channel. Please enable **Age-Restricted (18+)** for this channel or use the Download button below!",
                    view=view if "view" in locals() else discord.utils.MISSING,
                )
            else:
                await interaction.followup.send(embed=error_embed("Discord Error", str(e)))
        except Exception as e:
            log.exception("Error in /random tags=%s", tags)
            await interaction.followup.send(embed=error_embed("Error", str(e)))

    @cmd_random.autocomplete("tags")
    async def autocomplete_random_tags(self, interaction: discord.Interaction, current: str):
        return await self.tag_autocomplete(interaction, current)

    # ── /popular ──────────────────────────────────────────────────────────────
    @app_commands.command(name="popular", description="Browse popular posts on Danbooru")
    @app_commands.describe(
        scale="Timeframe: day, week, month",
        date="Specific date (YYYY-MM-DD, defaults to today)",
    )
    @app_commands.choices(scale=[
        app_commands.Choice(name="Today (Day)",   value="day"),
        app_commands.Choice(name="This Week",     value="week"),
        app_commands.Choice(name="This Month",    value="month"),
    ])
    async def cmd_popular(
        self,
        interaction: discord.Interaction,
        scale: str = "day",
        date: str = None,
    ):
        await interaction.response.defer()
        try:
            posts = await self.bot.booru.get_popular_posts(date=date, scale=scale, limit=4)
            if not posts:
                await interaction.followup.send(
                    embed=error_embed("No Data", "No popular posts found for the specified period.")
                )
                return
            scale_label = {"day": "today", "week": "this week", "month": "this month"}.get(scale, scale)
            session = await self.bot.booru._get_session()
            embeds = []
            files = []
            for p in posts:
                emb, f = await prepare_post_display(p, interaction.channel, self.booru_url, session)
                embeds.append(emb)
                if f:
                    files.append(f)
            view = MultiPostView(posts, self.booru_url) if len(posts) > 1 else PostView(posts[0], self.booru_url)
            send_kwargs = {
                "content": f"Popular posts for {scale_label} ({date or 'today'}):",
                "embeds": embeds,
                "view": view,
            }
            if files:
                send_kwargs["files"] = files
            await interaction.followup.send(**send_kwargs)
        except DanbooruError as e:
            await interaction.followup.send(embed=error_embed("API Error", e.message))
        except discord.errors.HTTPException as e:
            if e.code == 20009:
                await interaction.followup.send(
                    content="**Age-Restricted Content:** Discord blocked displaying this media in a regular channel. Please use an age-restricted channel or click the Download buttons below!",
                    view=view if "view" in locals() else discord.utils.MISSING,
                )
            else:
                await interaction.followup.send(embed=error_embed("Discord Error", str(e)))
        except Exception as e:
            log.exception("Error in /popular scale=%s", scale)
            await interaction.followup.send(embed=error_embed("Error", str(e)))

    # ── Auto-embed listener for Danbooru links in chat ─────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        matches = self.post_url_re.findall(message.content)
        if matches:
            embeds = []
            files = []
            fetched_posts = []
            session = await self.bot.booru._get_session()
            for post_id_str in matches[:3]:  # max 3 embeds per message
                try:
                    post = await self.bot.booru.get_post(int(post_id_str))
                    emb, f = await prepare_post_display(post, message.channel, self.booru_url, session)
                    embeds.append(emb)
                    if f:
                        files.append(f)
                    fetched_posts.append(post)
                except DanbooruError as e:
                    log.warning("Could not embed post %s: %s", post_id_str, e.message)
                except Exception as e:
                    log.warning("Error embedding post %s: %s", post_id_str, e)
            if embeds:
                view = MultiPostView(fetched_posts, self.booru_url) if len(fetched_posts) > 1 else PostView(fetched_posts[0], self.booru_url)
                reply_kwargs = {
                    "embeds": embeds,
                    "view": view,
                    "mention_author": False,
                }
                try:
                    if files:
                        reply_kwargs["files"] = files
                    await message.reply(**reply_kwargs)
                except discord.errors.HTTPException as e:
                    if e.code == 20009:
                        await message.reply(
                            content="**Age-Restricted Content:** Discord blocked direct preview of this image in a regular channel. Please view in an age-restricted channel or click Download!",
                            view=view,
                            mention_author=False,
                        )
                    else:
                        log.warning("Error replying with embed: %s", e)


async def setup(bot):
    await bot.add_cog(PostCommands(bot))
