"""
Smakbot: a small read-only HTTP endpoint saying what is playing, so other bots
on the same machine (Luna) can know without parsing chat messages.

    GET /now-playing[?guild=<id>]

Answers JSON for that guild's player (or the first one, without ?guild):

    {"playing": true, "paused": false, "title": "...", "artist": "...",
     "track": "...", "uploader": "...", "url": "...", "requested_by": "...",
     "elapsed": 73.2, "duration": 212.0, "voice_channel": "...",
     "up_next": ["...", "..."]}

or {"playing": false} when nothing is. Enabled with StatusApiPort (0 = off).
There is no authentication: publish the port on 127.0.0.1 only.
"""

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from aiohttp import web

if TYPE_CHECKING:
    from .bot import MusicBot
    from .player import MusicPlayer

log = logging.getLogger(__name__)

UP_NEXT_MAX = 5


def _info(entry: Any, key: str) -> Optional[str]:
    """A metadata field yt-dlp may have filled in, or None."""
    info = getattr(entry, "info", None)
    if info is None:
        return None
    try:
        value = info.get(key, None)
    except AttributeError:
        return None
    return str(value) if value else None


def describe_player(player: "MusicPlayer") -> Dict[str, Any]:
    """What one guild's player is doing, as plain JSON-able data."""
    entry = player.current_entry
    if entry is None or not (player.is_playing or player.is_paused):
        return {"playing": False}
    author = getattr(entry, "author", None)
    channel = getattr(player.voice_client, "channel", None)
    return {
        "playing": True,
        "paused": player.is_paused,
        "title": entry.title,
        # Song metadata, when the source has it (YouTube Music uploads often do).
        "artist": _info(entry, "artist") or _info(entry, "creator"),
        "track": _info(entry, "track"),
        "uploader": _info(entry, "uploader") or _info(entry, "channel"),
        "url": entry.url,
        "requested_by": author.display_name if author else None,
        "elapsed": round(player.progress, 1),
        "duration": entry.duration,
        "voice_channel": channel.name if channel else None,
        "up_next": [e.title for e in list(player.playlist.entries)[:UP_NEXT_MAX]],
    }


async def start_status_api(bot: "MusicBot", port: int) -> web.AppRunner:
    """Serve /now-playing on 0.0.0.0:port (inside the container)."""

    async def now_playing(request: web.Request) -> web.Response:
        guild_id = request.query.get("guild")
        player = None
        if guild_id and guild_id.isdigit():
            player = bot.players.get(int(guild_id))
        elif bot.players:
            player = next(iter(bot.players.values()))
        return web.json_response(describe_player(player) if player else {"playing": False})

    app = web.Application()
    app.router.add_get("/now-playing", now_playing)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("Status API: now playing at http://0.0.0.0:%s/now-playing", port)
    return runner
