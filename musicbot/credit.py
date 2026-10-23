"""
Smakbot: crediting a song to the person a trusted bot asked for it on behalf of.

Luna (a bot listed in BotExceptionIDs) relays people's voice requests as text
commands, so every song she queues was "added by Luna". She can end a command
with "--for=<@user id>" (a mention, shown as @name) or "--for=<user id>";
while that command runs, songs it queues are credited to that member ("added
by", /now-playing, round-robin order). Credit only: the command still runs as
Luna, with Luna's permissions.
"""

from contextvars import ContextVar
from typing import Optional

import discord

# Set by on_message for one command; a context variable, so it follows that
# command's own task (and tasks it starts) and nothing else.
credit_for: ContextVar[Optional[discord.Member]] = ContextVar("credit_for", default=None)


def credited(author: Optional[discord.Member]) -> Optional[discord.Member]:
    """The member a song is credited to: the --for member when a bot queued it."""
    member = credit_for.get()
    if member is not None and author is not None and author.bot:
        return member
    return author
