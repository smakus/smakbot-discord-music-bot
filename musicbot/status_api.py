"""
Smakbot: a small read-only HTTP endpoint saying what is playing, so other bots
on the same machine (Luna) can know without parsing chat messages.

    GET /now-playing[?guild=<id>]

Answers JSON for that guild's player (or the first one, without ?guild):

    {"playing": true, "paused": false, "title": "...", "artist": "...",
     "track": "...", "uploader": "...", "url": "...", "requested_by": "...",
     "elapsed": 73.2, "duration": 212.0, "voice_channel": "...",
     "up_next": ["...", "..."]}

or {"playing": false} when nothing is.

    GET /top-songs[?count=<n>]

The most played songs in the audio cache, the same list !playtop queues
(count 1-50, default 10):

    {"songs": [{"title": "...", "plays": 13}, ...]}

    GET /top-songs?user=<name, user ID or mention>[&count=<n>]

The songs that person asked for most (request_history.py), whether or not
they are online. The name may be loose ("smak", "smackus"):

    {"user": "smakus", "songs": [{"title": "...", "requests": 4}, ...]}

or, when the name doesn't pick out one person,
{"user": null, "matches": ["closest", "names"]} (empty: nobody like that).
A known person who hasn't asked for anything yet gets "songs": [].

Enabled with StatusApiPort (0 = off).
There is no authentication: publish the port on 127.0.0.1 only.
"""

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from aiohttp import web

if TYPE_CHECKING:
    from .bot import MusicBot
    from .player import MusicPlayer

log = logging.getLogger(__name__)

UP_NEXT_MAX = 5
TOP_SONGS_MAX = 50


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


def top_songs(bot: "MusicBot", count: int) -> List[Dict[str, Any]]:
    """The `count` most played cached songs, titles and play counts."""
    return [
        {
            "title": stats.get("title") or bot.filecache.title_from_filename(path.name),
            "plays": int(stats.get("plays", 0)),
        }
        for path, stats in bot.filecache.most_played(count)
    ]


def _members(bot: "MusicBot", guild_id: Optional[str]) -> List[Tuple[int, List[str]]]:
    """(id, names) of the server members, online or not, bots left out."""
    guilds = bot.guilds
    if guild_id and guild_id.isdigit():
        guilds = [g for g in guilds if g.id == int(guild_id)] or guilds
    members = []
    for guild in guilds:
        for m in guild.members:
            if not m.bot:
                members.append((m.id, [m.display_name, m.global_name or "", m.name]))
    return members


def user_top_songs(
    bot: "MusicBot", said: str, count: int, guild_id: Optional[str] = None
) -> Dict[str, Any]:
    """The songs the person `said` names asked for most (see the docstring)."""
    members = _members(bot, guild_id)
    user_id, matches = bot.request_history.find_user(said, members)
    if user_id is None:
        return {"user": None, "matches": matches}
    name = bot.request_history.name_of(user_id)
    if name is None:
        name = next((ns[0] for uid, ns in members if uid == user_id), str(user_id))
    return {"user": name, "songs": bot.request_history.top(user_id, count)}


async def start_status_api(bot: "MusicBot", port: int) -> web.AppRunner:
    """Serve /now-playing and /top-songs on 0.0.0.0:port (inside the container)."""

    async def now_playing(request: web.Request) -> web.Response:
        guild_id = request.query.get("guild")
        player = None
        if guild_id and guild_id.isdigit():
            player = bot.players.get(int(guild_id))
        elif bot.players:
            player = next(iter(bot.players.values()))
        return web.json_response(describe_player(player) if player else {"playing": False})

    async def top(request: web.Request) -> web.Response:
        try:
            count = int(request.query.get("count", "10"))
        except ValueError:
            count = 10
        count = max(1, min(count, TOP_SONGS_MAX))
        user = request.query.get("user", "").strip()
        if user:
            return web.json_response(
                user_top_songs(bot, user, count, request.query.get("guild"))
            )
        return web.json_response({"songs": top_songs(bot, count)})

    app = web.Application()
    app.router.add_get("/now-playing", now_playing)
    app.router.add_get("/top-songs", top)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("Status API: http://0.0.0.0:%s/now-playing and /top-songs", port)
    return runner
