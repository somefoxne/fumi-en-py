"""
Cog managing analytics, reports, and count commands on Danbooru.
Includes:
  /top_uploaders – ASCII box-drawing table of top 25 uploaders
  /count         – Count total matching posts for a query
  /daily_upload  – Daily upload rate, % share, and total posts for a tag
"""

import asyncio
from datetime import datetime, timezone
import logging
import urllib.parse
import discord
from discord import app_commands
from discord.ext import commands

import settings
from danbooru_client import DanbooruError
from embeds import (
    error_embed,
    render_top_uploaders_table,
    TAG_COLORS,
    TAG_CATEGORY_NAMES,
    _image_url,
    is_nsfw_channel,
)

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
                estimated = await self.bot.booru.estimate_post_count(tags=tags)
                if estimated is not None:
                    est_str = f"📊 **Estimated count:** `~{estimated:,}` posts *(1,000-sample Monte Carlo)*\n\n"
                else:
                    est_str = ""

                embed = discord.Embed(
                    title="📊 Unable to Calculate Exact Post Count",
                    description=(
                        f"⚠️ Danbooru timed out calculating the exact count for {label}.\n\n"
                        f"{est_str}"
                        f"**Reason:** Complex searches with negative tags (`-`) or wildcards (`*`) "
                        f"are too resource-intensive for Danbooru database to scan accurately.\n"
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

    # ── /daily_upload ─────────────────────────────────────────────────────────
    @app_commands.command(
        name="daily_upload",
        description="Show average daily upload rate, % upload share, and total posts for a tag.",
    )
    @app_commands.describe(tag="Tag name to inspect (e.g. frieren, 1girl)")
    async def cmd_daily_upload(self, interaction: discord.Interaction, tag: str):
        await interaction.response.defer()
        try:
            clean_tag = tag.strip().lower()
            if not clean_tag:
                await interaction.followup.send(embed=error_embed("Error", "Please provide a tag name."))
                return

            search_url = f"{self.booru_url}/posts?tags={urllib.parse.quote(clean_tag)}"

            # Run parallel requests to optimize response latency (< 1s)
            is_single_tag = len(clean_tag.split()) == 1
            tasks = [
                self.bot.booru.get_post_count(tags=clean_tag),
                self.bot.booru.get_post_count(tags=""),
                self.bot.booru.get_posts(tags=clean_tag, limit=1, page="a0", only="id,created_at,rating,media_asset,file_url,large_file_url"),
                self.bot.booru.get_posts(tags=clean_tag, limit=1, page=1, only="id,created_at,rating,media_asset,file_url,large_file_url"),
            ]
            if is_single_tag:
                tasks.append(self.bot.booru.get_tag(clean_tag))
                tasks.append(self.bot.booru.get_post_count(tags=f"{clean_tag} age:<30d"))
                tasks.append(self.bot.booru.get_post_count(tags="age:<30d"))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            count_res = results[0]
            total_booru_res = results[1]
            oldest_posts = results[2]
            newest_posts = results[3]

            tag_info = results[4] if is_single_tag and len(results) > 4 and isinstance(results[4], dict) else None
            recent_count = results[5] if is_single_tag and len(results) > 5 and isinstance(results[5], int) else None
            recent_booru_count = results[6] if is_single_tag and len(results) > 6 and isinstance(results[6], int) else None

            # Determine total tag posts
            total_posts = 0
            if isinstance(count_res, int) and count_res is not None:
                total_posts = count_res
            elif tag_info and tag_info.get("post_count"):
                total_posts = tag_info["post_count"]
            elif isinstance(oldest_posts, list) and oldest_posts:
                total_posts = len(oldest_posts)

            if total_posts == 0 or not isinstance(oldest_posts, list) or not oldest_posts:
                embed = discord.Embed(
                    title="📊 Daily Upload Stats",
                    description=f"No posts found for tag `{clean_tag}` on Danbooru.",
                    color=0xED4245,
                )
                embed.set_footer(text=f"danbooru • {self.booru_url}")
                await interaction.followup.send(embed=embed)
                return

            # Determine total Danbooru posts
            total_booru = total_booru_res if (isinstance(total_booru_res, int) and total_booru_res > 0) else 8_600_000
            pct_upload = (total_posts / total_booru) * 100.0

            # Calculate lifespan and upload rate
            first_post = oldest_posts[0]
            latest_post = newest_posts[0] if (isinstance(newest_posts, list) and newest_posts) else first_post

            now = datetime.now(timezone.utc)
            first_created = datetime.fromisoformat(first_post["created_at"].replace("Z", "+00:00"))
            latest_created = datetime.fromisoformat(latest_post["created_at"].replace("Z", "+00:00"))

            delta_days = max((now - first_created).total_seconds() / 86400.0, 0.0416)
            daily_avg = total_posts / delta_days

            if delta_days < 1.0:
                duration_str = "< 1 day"
            elif delta_days < 365:
                duration_str = f"{int(delta_days):,} days"
            else:
                years = delta_days / 365.25
                duration_str = f"{years:.1f} years ({int(delta_days):,} days)"

            # Styling based on tag category
            category_id = tag_info.get("category", 0) if tag_info else 0
            cat_name = TAG_CATEGORY_NAMES.get(category_id, "General") if is_single_tag else None
            embed_color = TAG_COLORS.get(category_id, 0x5865F2) if is_single_tag else 0x5865F2

            embed = discord.Embed(
                title=f"📊 Daily Upload Stats • {clean_tag}",
                url=search_url,
                color=embed_color,
                timestamp=discord.utils.utcnow(),
            )

            desc_lines = []
            if cat_name:
                desc_lines.append(f"🏷️ Category: **{cat_name}**")
            desc_lines.append(f"🔗 [View all posts on Danbooru]({search_url})")
            embed.description = "\n".join(desc_lines)

            # 1. Total Posts
            embed.add_field(
                name="📦 Total Posts",
                value=f"**{total_posts:,}** posts",
                inline=True,
            )

            # 2. % of Total Uploads
            pct_str = f"{pct_upload:.4f}%" if pct_upload < 0.01 else f"{pct_upload:.2f}%"
            embed.add_field(
                name="📈 % of Total Uploads",
                value=f"**{pct_str}** *(out of {total_booru:,} posts)*",
                inline=True,
            )

            # 3. All-time Daily Average
            rate_str = (
                f"~{daily_avg:,.1f}"
                if daily_avg >= 10
                else (f"~{daily_avg:.2f}" if daily_avg >= 0.1 else f"~{daily_avg:.4f}")
            )
            embed.add_field(
                name="⚡ All-time Daily Average",
                value=f"**{rate_str}** posts/day\n*(over {duration_str})*",
                inline=False,
            )

            # 4. Recent Activity (30 days)
            if recent_count is not None:
                recent_daily = recent_count / 30.0
                recent_rate_str = f"~{recent_daily:,.1f}" if recent_daily >= 10 else f"~{recent_daily:.2f}"
                extra_note = ""
                if recent_booru_count and recent_booru_count > 0:
                    recent_share = (recent_count / recent_booru_count) * 100.0
                    extra_note = f" • {recent_share:.2f}% of recent uploads"
                embed.add_field(
                    name="🔥 Recent Activity (Past 30 days)",
                    value=f"**{recent_rate_str}** posts/day\n*({recent_count:,} posts in past 30 days{extra_note})*",
                    inline=False,
                )

            # 5. Timeline
            first_ts = int(first_created.timestamp())
            latest_ts = int(latest_created.timestamp())
            first_link = f"[#{first_post['id']}]({self.booru_url}/posts/{first_post['id']})"
            latest_link = f"[#{latest_post['id']}]({self.booru_url}/posts/{latest_post['id']})"
            embed.add_field(
                name="📅 Timeline",
                value=(
                    f"• **First post:** {first_link} (<t:{first_ts}:d> • <t:{first_ts}:R>)\n"
                    f"• **Latest post:** {latest_link} (<t:{latest_ts}:d> • <t:{latest_ts}:R>)"
                ),
                inline=False,
            )

            # Safe preview thumbnail
            if is_nsfw_channel(interaction.channel) or latest_post.get("rating") == "g":
                thumb_url = _image_url(latest_post)
                if thumb_url:
                    embed.set_thumbnail(url=thumb_url)

            embed.set_footer(text=f"danbooru • {self.booru_url}")
            await interaction.followup.send(embed=embed)
        except DanbooruError as e:
            await interaction.followup.send(embed=error_embed("API Error", e.message))
        except Exception as e:
            log.exception("Error in /daily_upload tag=%s", tag)
            await interaction.followup.send(embed=error_embed("Error", str(e)))

    # Autocomplete delegates
    @cmd_count.autocomplete("tags")
    @cmd_top_uploaders.autocomplete("tags")
    @cmd_daily_upload.autocomplete("tag")
    async def autocomplete_tags_delegate(self, interaction: discord.Interaction, current: str):
        return await self.tag_autocomplete(interaction, current)


async def setup(bot):
    await bot.add_cog(ReportCommands(bot))
