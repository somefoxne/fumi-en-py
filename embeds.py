"""
Embed builders and interactive UI Views for Discord.
Reference: danbooru/fumimi-discord
- No tag spam in post embeds
- Download button for direct full-resolution image access
- Automatic spoiler / content concealment for Rating Q/E posts in non-NSFW channels
"""

import io
import re
import aiohttp
import discord
from typing import Optional
import unicodedata

# ── Tag Category Colors ────────────────────────────────────────────────────────
TAG_COLORS = {
    0: 0xB0C4DE,  # General   – light steel blue
    1: 0xFF0000,  # Artist    – red
    3: 0x9400D3,  # Copyright – purple
    4: 0x00AA00,  # Character – green
    5: 0xFF8C00,  # Meta      – dark orange
}

TAG_CATEGORY_NAMES = {
    0: "General",
    1: "Artist",
    3: "Copyright",
    4: "Character",
    5: "Meta",
}

RATING_LABELS = {
    "g": "General",
    "s": "Sensitive",
    "q": "Questionable",
    "e": "Explicit",
}

RATING_COLORS = {
    "g": 0x00AA00,
    "s": 0xFFD700,
    "q": 0xFF8C00,
    "e": 0xFF0000,
}

NON_IMAGE_EXT = {".swf", ".zip", ".mp4", ".webm"}


def is_nsfw_channel(channel) -> bool:
    """Check if the channel has Age-Restricted (NSFW) enabled."""
    if channel is None:
        return False
    if hasattr(channel, "is_nsfw"):
        try:
            return bool(channel.is_nsfw())
        except TypeError:
            return bool(getattr(channel, "is_nsfw", False))
    return bool(getattr(channel, "nsfw", False))


def _image_url(post: dict) -> Optional[str]:
    """Get the appropriate preview or sample image URL for embed display."""
    media = post.get("media_asset") or {}
    variants = media.get("variants") or []
    # Priority: 720x → sample → original
    for size in ("720x", "sample", "original"):
        for v in variants:
            if v.get("type") == size:
                url = v.get("url", "")
                if not any(url.endswith(ext) for ext in NON_IMAGE_EXT):
                    return url
    # Fallback
    for key in ("large_file_url", "file_url"):
        url = media.get(key) or post.get(key, "")
        if url and not any(url.endswith(ext) for ext in NON_IMAGE_EXT):
            return url
    return None


def get_download_url(post: dict, booru_url: str = "https://danbooru.donmai.us") -> Optional[str]:
    """Get highest quality direct image download URL (original preferred)."""
    media = post.get("media_asset") or {}
    variants = media.get("variants") or []
    for v in variants:
        if v.get("type") == "original":
            return v.get("url")
    for v in variants:
        if v.get("type") == "sample":
            return v.get("url")
    for key in ("file_url", "large_file_url"):
        url = media.get(key) or post.get(key)
        if url:
            return url
    return _image_url(post) or (f"{booru_url}/posts/{post.get('id')}" if post.get("id") else None)


def post_embed(
    post: dict,
    booru_url: str = "https://danbooru.donmai.us",
    spoiler_filename: Optional[str] = None,
) -> discord.Embed:
    """Build an embed for a single Danbooru post."""
    post_id = post.get("id")
    rating  = str(post.get("rating", "g")).lower()
    color   = RATING_COLORS.get(rating, 0xB0C4DE)
    url     = f"{booru_url}/posts/{post_id}"

    embed = discord.Embed(title=f"Post #{post_id}", url=url, color=color)

    if spoiler_filename:
        embed.set_image(url=f"attachment://{spoiler_filename}")
        embed.description = "*(Content blurred: Channel is not age-restricted. Click image to reveal)*"
    else:
        img = _image_url(post)
        if img:
            embed.set_image(url=img)

    # Metadata fields
    embed.add_field(name="Rating", value=RATING_LABELS.get(rating, rating.upper()), inline=True)
    embed.add_field(name="Score",  value=f"{post.get('score', 0):+}",               inline=True)
    embed.add_field(name="Favs",   value=f"{post.get('fav_count', 0):,}",            inline=True)

    # Uploader
    uploader = post.get("uploader")
    if isinstance(uploader, dict) and uploader:
        uname = uploader.get("name") or f"User #{uploader.get('id', '?')}"
        uid   = uploader.get("id")
        ulink = f"[{uname}]({booru_url}/users/{uid})" if uid else uname
    elif post.get("uploader_name"):
        uname = post.get("uploader_name")
        uid   = post.get("uploader_id")
        ulink = f"[{uname}]({booru_url}/users/{uid})" if uid else uname
    elif post.get("uploader_id"):
        uid = post.get("uploader_id")
        ulink = f"[User #{uid}]({booru_url}/users/{uid})"
    elif uploader:
        ulink = str(uploader)
    else:
        ulink = "Unknown"
    embed.add_field(name="Uploader", value=ulink, inline=True)

    # Source
    source = post.get("source", "")
    if source and len(source) < 200:
        embed.add_field(name="Source", value=source, inline=False)

    embed.set_footer(text=f"danbooru • Post #{post_id} • Rating: {RATING_LABELS.get(rating, rating)}")
    return embed


async def prepare_post_display(
    post: dict,
    channel,
    booru_url: str = "https://danbooru.donmai.us",
    session: Optional[aiohttp.ClientSession] = None,
) -> tuple[discord.Embed, Optional[discord.File]]:
    """
    Handle post presentation based on channel NSFW status:
    - If rating is Questionable or Explicit in non-NSFW channel:
      Hide image to avoid Discord error 20009 and provide download button.
    - If channel is age-restricted or post is safe:
      Display inline image normally.
    """
    post_id = post.get("id", 0)
    rating  = str(post.get("rating", "g")).lower()
    is_nsfw = is_nsfw_channel(channel)

    needs_hide = (rating in ("q", "e")) and (not is_nsfw)

    if needs_hide:
        embed = post_embed(post, booru_url)
        embed.set_image(url=None)
        embed.description = (
            "**Age-Restricted Content (Rating Q/E)**\n"
            "*Image preview hidden because this channel is not marked as **Age-Restricted (18+)**.\n"
            "Enable 18+ channel settings or click **Download** below to view.*"
        )
        return embed, None

    return post_embed(post, booru_url), None


# ── Interactive Buttons & Views ────────────────────────────────────────────────

class PostView(discord.ui.View):
    """View containing Download and Post link buttons."""
    def __init__(self, post: dict, booru_url: str = "https://danbooru.donmai.us"):
        super().__init__(timeout=None)
        download_url = get_download_url(post, booru_url)
        if download_url:
            self.add_item(
                discord.ui.Button(
                    label="Download",
                    style=discord.ButtonStyle.link,
                    url=download_url,
                )
            )
        post_id = post.get("id")
        if post_id:
            self.add_item(
                discord.ui.Button(
                    label=f"Post #{post_id}",
                    style=discord.ButtonStyle.link,
                    url=f"{booru_url}/posts/{post_id}",
                )
            )


class MultiPostView(discord.ui.View):
    """View containing Download buttons when multiple posts are displayed."""
    def __init__(self, posts: list[dict], booru_url: str = "https://danbooru.donmai.us"):
        super().__init__(timeout=None)
        for i, post in enumerate(posts[:5], start=1):
            download_url = get_download_url(post, booru_url)
            post_id = post.get("id", i)
            if download_url:
                self.add_item(
                    discord.ui.Button(
                        label=f"Download #{post_id}",
                        style=discord.ButtonStyle.link,
                        url=download_url,
                    )
                )


def tag_embed(
    tag: dict,
    wiki: dict = None,
    booru_url: str = "https://danbooru.donmai.us",
) -> discord.Embed:
    """Build an embed for tag metadata and wiki summary."""
    name       = tag.get("name", "unknown")
    category   = tag.get("category", 0)
    color      = TAG_COLORS.get(category, 0xB0C4DE)
    post_count = tag.get("post_count", 0)
    cat_name   = TAG_CATEGORY_NAMES.get(category, "Unknown")

    target_url = f"{booru_url}/wiki_pages/{name}" if wiki else f"{booru_url}/posts?tags={name}"
    embed = discord.Embed(
        title=name.replace("_", " "),
        url=target_url,
        color=color,
    )

    embed.add_field(name="Posts",    value=f"[{post_count:,}]({booru_url}/posts?tags={name})", inline=True)
    embed.add_field(name="Category", value=cat_name, inline=True)

    if tag.get("is_deprecated"):
        antecedent = (tag.get("antecedent_alias") or {}).get("antecedent_name", "")
        embed.add_field(
            name="Deprecated",
            value=f"Use `{antecedent}` instead." if antecedent else "This tag has been deprecated.",
            inline=False,
        )

    if wiki:
        body = wiki.get("body", "")
        if body:
            body = re.sub(r"\[\[(.+?)(?:\|.+?)?\]\]", r"\1", body)
            body = re.sub(r"\[b\](.+?)\[/b\]", r"**\1**", body)
            body = re.sub(r"h\d\.\s*", "", body)
            preview = truncate(body.strip(), 800)
            embed.add_field(name="Wiki", value=preview, inline=False)

    embed.set_footer(text=f"danbooru • {name}")
    return embed


def error_embed(title: str, description: str) -> discord.Embed:
    return discord.Embed(title=f"Error: {title}", description=description, color=0xFF0000)


def info_embed(title: str, description: str, color: int = 0x5865F2) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=color)


def truncate(text: str, max_len: int = 1024) -> str:
    """Truncate text to fit Discord embed field length limits."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


# ── ASCII Box-Drawing Table Renderer (Fumimi Ruby Compatible) ──────────────────

def str_display_width(s: str) -> int:
    """Calculate actual terminal display width handling full-width East Asian chars."""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in str(s))


def pad_display(s: str, w: int) -> str:
    """Pad string taking double-width characters into account."""
    s_str = str(s)
    return s_str + " " * max(0, w - str_display_width(s_str))


def truncate_display(s: str, max_w: int = 19) -> str:
    """Truncate string without breaking table column alignment."""
    s_str = str(s)
    if str_display_width(s_str) <= max_w:
        return s_str
    cur = ""
    for ch in s_str:
        if str_display_width(cur + ch) + 1 > max_w:
            return cur + "…"
        cur += ch
    return cur


def render_top_uploaders_table(headers: list[str], rows: list[list[str]]) -> str:
    """Format ASCII box-drawing table matching the Ruby Fumimi bot output."""
    clean_rows = []
    for r in rows:
        clean_row = []
        for i, cell in enumerate(r):
            c_str = str(cell)
            if i == 0:
                c_str = truncate_display(c_str, 19)
            clean_row.append(c_str)
        clean_rows.append(clean_row)

    col_widths = []
    for i, h in enumerate(headers):
        max_w = str_display_width(h)
        for r in clean_rows:
            if i < len(r):
                max_w = max(max_w, str_display_width(r[i]))
        col_widths.append(max_w)

    top = "┌" + "┬".join("─" * (w + 2) for w in col_widths) + "┐"
    header_line = "│" + "│".join(f" {pad_display(h, w)} " for h, w in zip(headers, col_widths)) + "│"
    mid = "├" + "┼".join("─" * (w + 2) for w in col_widths) + "┤"
    row_lines = [
        "│" + "│".join(f" {pad_display(val, w)} " for val, w in zip(r, col_widths)) + "│"
        for r in clean_rows
    ]
    bot = "└" + "┴".join("─" * (w + 2) for w in col_widths) + "┘"

    table_content = "\n".join([top, header_line, mid] + row_lines + [bot])
    forced_width = "-" * 80
    return f"```\n{table_content}\n```\n{forced_width}"
