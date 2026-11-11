"""
Smakbot: who asked for which songs, kept so "what are smakus's top songs?" has
an answer even when that person is offline.

Every song a person queues is counted once for them when it is added to the
queue (credited through Luna's --for when she relays it). Not counted: songs
the auto playlist adds, songs queued by bots on their own behalf, and the
re-queued favourites of !playtop (those are everyone's, not a request).

Kept in config/request_history.json (the config folder is a mounted volume,
so it survives rebuilds; the audio cache can be cleared, this shouldn't be):

    {"users": {"<user id>": {"name": "smakus", "username": "smakus",
        "songs": {"<url or title>": {"title": "...", "url": "...",
                                       "count": 3, "last": 1731300000.0}}}}}

Plain Python, no Discord objects inside, so it can be tested on its own.
"""

import difflib
import json
import logging
import pathlib
import re
import time
from contextvars import ContextVar
from typing import Any, Dict, Iterable, List, Optional, Tuple

log = logging.getLogger(__name__)

REQUEST_HISTORY_FILE = "request_history.json"

# Set while a command queues songs that aren't anyone's request (!playtop).
not_a_request: ContextVar[bool] = ContextVar("not_a_request", default=False)

# How close a spoken or misspelled name must be to count as a match (0-1).
FUZZY_CUTOFF = 0.75


def _norm(name: str) -> str:
    """A name for matching: lower case, letters and digits only."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def song_key(title: str, url: str) -> str:
    """One song, however it was asked for: its web address, else its title."""
    if url and url.startswith(("http://", "https://")):
        return url
    return "title:" + (title or "").strip().lower()


class RequestHistory:
    """Per-person request counts, saved to a JSON file after every change."""

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        self._users: Optional[Dict[str, Dict[str, Any]]] = None

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if self._users is not None:
            return self._users
        self._users = {}
        try:
            with open(self.path, "r", encoding="utf8") as fh:
                users = json.load(fh).get("users", {})
            if isinstance(users, dict):
                self._users = users
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AttributeError):
            log.warning("Could not read the request history:  %s", self.path)
        return self._users

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf8") as fh:
                json.dump({"users": self._load()}, fh)
            tmp.replace(self.path)
        except OSError:
            log.warning("Could not save the request history.", exc_info=True)

    def record(
        self,
        user_id: int,
        name: str,
        username: str,
        title: str,
        url: str,
        when: Optional[float] = None,
    ) -> None:
        """Count one request of a song by one person."""
        if not user_id or not (title or url):
            return
        user = self._load().setdefault(str(user_id), {"songs": {}})
        user["name"] = name or user.get("name") or username
        user["username"] = username or user.get("username") or name
        song = user.setdefault("songs", {}).setdefault(
            song_key(title, url), {"count": 0}
        )
        song["count"] = int(song.get("count", 0)) + 1
        song["last"] = when if when is not None else time.time()
        if title:
            song["title"] = title
        if url and url.startswith(("http://", "https://")):
            song["url"] = url
        self._save()

    def name_of(self, user_id: int) -> Optional[str]:
        """The name a person had when they last asked for a song."""
        user = self._load().get(str(user_id))
        return user.get("name") if user else None

    def top(self, user_id: int, count: int) -> List[Dict[str, Any]]:
        """A person's most requested songs, most first (ties: most recent first)."""
        user = self._load().get(str(user_id))
        if not user:
            return []
        songs = sorted(
            user.get("songs", {}).values(),
            key=lambda s: (-int(s.get("count", 0)), -float(s.get("last", 0))),
        )
        return [
            {"title": s.get("title") or s.get("url", ""), "requests": int(s.get("count", 0))}
            for s in songs[:count]
        ]

    def find_user(
        self, said: str, members: Iterable[Tuple[int, Iterable[str]]] = ()
    ) -> Tuple[Optional[int], List[str]]:
        """
        Who a name means: (user id, []) when it is clear, or (None, the closest
        names) when it isn't. `said` may be a user ID, a mention, or a name as
        typed or heard ("smakus", "Smak", "smackus"). Looks at everyone in the
        history and at `members`: (id, [their names]) of the server's members,
        online or not, so a person who never asked for a song is still known.
        """
        said = (said or "").strip()
        mention = re.fullmatch(r"<@!?(\d{5,25})>|(\d{5,25})", said)
        if mention:
            return int(mention.group(1) or mention.group(2)), []

        names: Dict[int, List[str]] = {}
        for uid, user in self._load().items():
            if uid.isdigit():
                names.setdefault(int(uid), []).extend(
                    n for n in (user.get("name"), user.get("username")) if n
                )
        for uid, member_names in members:
            names.setdefault(int(uid), []).extend(n for n in member_names if n)

        target = _norm(said)
        if not target:
            return None, []

        def best(test) -> List[int]:
            return [uid for uid, ns in names.items() if any(test(_norm(n)) for n in ns)]

        # Exact, then the start of a name ("smak" → smakus), then fuzzy ("smackus").
        for test in (
            lambda n: n == target,
            lambda n: len(target) >= 3 and n.startswith(target),
        ):
            found = best(test)
            if len(found) == 1:
                return found[0], []
            if len(found) > 1:
                # Prefer whoever has asked for songs.
                asked = [uid for uid in found if str(uid) in self._load()]
                if len(asked) == 1:
                    return asked[0], []
                return None, sorted({names[uid][0] for uid in found})

        scored = []
        for uid, ns in names.items():
            score = max(
                (difflib.SequenceMatcher(None, target, _norm(n)).ratio() for n in ns),
                default=0,
            )
            if score >= FUZZY_CUTOFF:
                scored.append((score, uid))
        scored.sort(reverse=True)
        if len(scored) == 1 or (len(scored) > 1 and scored[0][0] - scored[1][0] >= 0.1):
            return scored[0][1], []
        return None, [names[uid][0] for _, uid in scored[:5]]
