import asyncio
import glob
import json
import logging
import math
import os
import pathlib
import shutil
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from . import write_path
from .constants import (
    AUDIO_CACHE_INDEX_FILE,
    AUDIO_CACHE_LOUDNESS_FILE,
    AUDIO_CACHE_SEARCH_MEMORY_FILE,
    CACHE_NEW_FILE_GRACE_SECONDS,
    CACHE_PLAY_BONUS_DAYS,
    CACHE_SWEEP_TARGET_RATIO,
    DATA_FILE_CACHEMAP,
    DEFAULT_DATA_DIR,
)
from .utils import format_size_from_bytes

if TYPE_CHECKING:
    from .bot import MusicBot
    from .config import Config
    from .entry import BasePlaylistEntry, URLPlaylistEntry

log = logging.getLogger(__name__)


class AudioFileCache:
    """
    This class provides methods to manage the audio file cache and get info about it.
    """

    def __init__(self, bot: "MusicBot") -> None:
        """
        Manage data related to the audio cache, such as its current size,
        file count, file paths, and synchronization locks.
        """
        self.bot: MusicBot = bot
        self.config: Config = bot.config
        self.cache_path: pathlib.Path = bot.config.audio_cache_path
        self.cachemap_file = write_path(DEFAULT_DATA_DIR).joinpath(DATA_FILE_CACHEMAP)

        self.size_bytes: int = 0
        self.file_count: int = 0
        self._index: Optional[Dict[str, Dict[str, float]]] = None
        self._search_memory: Optional[Dict[str, Dict[str, Any]]] = None

        # Stores filenames without extension associated to a playlist URL.
        self.auto_playlist_cachemap: Dict[str, str] = {}
        self.cachemap_file_lock: asyncio.Lock = asyncio.Lock()
        self.cachemap_defer_write: bool = False

        if self.config.auto_playlist:
            self.load_autoplay_cachemap()

    @property
    def folder(self) -> pathlib.Path:
        """Get the configured cache path as a pathlib.Path"""
        return self.cache_path

    @property
    def index_file(self) -> pathlib.Path:
        """Path of the JSON index holding play stats and loudness for cached files."""
        return self.cache_path / AUDIO_CACHE_INDEX_FILE

    def _load_index(self) -> Dict[str, Dict[str, float]]:
        """Load the cache index once, migrating the older loudness-only file."""
        if self._index is not None:
            return self._index
        self._index = {}
        for path in (self.cache_path / AUDIO_CACHE_LOUDNESS_FILE, self.index_file):
            try:
                with open(path, "r", encoding="utf8") as fh:
                    for name, data in json.load(fh).items():
                        self._index.setdefault(name, {}).update(data)
            except FileNotFoundError:
                pass
            except (OSError, ValueError):
                log.warning("Could not read cache index file:  %s", path)
        # make sure every cached file has play stats, so the index is complete.
        if self.cache_path.is_dir():
            for item in self.cache_path.iterdir():
                if (
                    item.is_file()
                    and not item.name.startswith(".")
                    and item.suffix not in (".part", ".ytdl", ".tmp")
                ):
                    self._index_entry(item.name)
        return self._index

    def _save_index(self) -> None:
        """Write the cache index to disk, and retire the older loudness file."""
        index = self._load_index()
        try:
            self.ensure_cache_dir_exists()
            tmp = self.index_file.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf8") as fh:
                json.dump(index, fh)
            tmp.replace(self.index_file)
            (self.cache_path / AUDIO_CACHE_LOUDNESS_FILE).unlink(missing_ok=True)
        except OSError:
            log.warning("Could not save the cache index.", exc_info=True)

    def _index_entry(self, filename: str) -> Dict[str, float]:
        """
        Get (creating if needed) the index entry for a cached file, filling in
        play stats it doesn't have yet from the file itself.
        """
        path = self.cache_path / pathlib.Path(filename).name
        entry = self._load_index().setdefault(path.name, {})
        if "created" not in entry:
            try:
                entry["created"] = os.stat(path).st_ctime
            except OSError:
                entry["created"] = time.time()
        entry.setdefault("last_played", entry["created"])
        entry.setdefault("plays", 0)
        return entry

    def get_loudness(self, filename: str) -> Optional[Dict[str, float]]:
        """
        Get the stored loudness measurement for a cached file, keyed by basename.
        Returns a dict with 'i' (LUFS) and 'tp' (dBTP), or None if not measured.
        """
        entry = self._load_index().get(pathlib.Path(filename).name, {})
        if "i" in entry and "tp" in entry:
            return {"i": entry["i"], "tp": entry["tp"]}
        return None

    def set_loudness(self, filename: str, i_lufs: float, tp_dbtp: float) -> None:
        """Store a loudness measurement for a cached file and save the index."""
        entry = self._index_entry(filename)
        entry["i"] = i_lufs
        entry["tp"] = tp_dbtp
        self._save_index()

    def record_play(
        self,
        filename: str,
        title: str = "",
        url: str = "",
        duration: Optional[float] = None,
    ) -> None:
        """
        Count a play of a cached file and mark it as played now.
        Song details are kept too, so the file can be queued again from cache.
        """
        if not filename or not (self.cache_path / pathlib.Path(filename).name).is_file():
            return
        entry = self._index_entry(filename)
        entry["plays"] = int(entry["plays"]) + 1
        entry["last_played"] = time.time()
        if title:
            entry["title"] = title
        if url and not url.startswith("file://"):
            entry["url"] = url
        if duration:
            entry["duration"] = duration
        self._save_index()

    def most_played(self, count: int) -> List[Tuple[pathlib.Path, Dict[str, Any]]]:
        """
        Cached files that have been played, most plays first (ties: most
        recently played first), limited to `count`.
        """
        played = []
        for name, entry in self._load_index().items():
            path = self.cache_path / name
            if int(entry.get("plays", 0)) > 0 and path.is_file():
                played.append((path, entry))
        played.sort(key=lambda p: (-int(p[1]["plays"]), -float(p[1]["last_played"])))
        return played[:count]

    @staticmethod
    def title_from_filename(filename: str) -> str:
        """Best-effort song title from a cache filename like youtube-<id>-<title>-NA.ext"""
        stem = pathlib.Path(filename).stem
        if stem.startswith("youtube-") and len(stem) > 20:
            stem = stem[20:]
        if stem.endswith("-NA"):
            stem = stem[:-3]
        return stem.replace("_", " ").strip() or pathlib.Path(filename).name

    def keep_until(self, filename: str) -> float:
        """
        Timestamp used to order the cache sweep: the last play, plus a bonus of
        CACHE_PLAY_BONUS_DAYS for every doubling of the play count.
        """
        entry = self._index_entry(filename)
        bonus_days = CACHE_PLAY_BONUS_DAYS * math.log2(max(1, int(entry["plays"])))
        return float(entry["last_played"]) + bonus_days * 86400

    @staticmethod
    def normalize_search(query: str) -> str:
        """Normalize search text so trivial differences map to the same memory."""
        return " ".join(query.lower().split())

    def _load_search_memory(self) -> Dict[str, Dict[str, Any]]:
        """Load remembered search results once."""
        if self._search_memory is None:
            self._search_memory = {}
            try:
                with open(
                    self.cache_path / AUDIO_CACHE_SEARCH_MEMORY_FILE, "r", encoding="utf8"
                ) as fh:
                    self._search_memory = json.load(fh)
            except FileNotFoundError:
                pass
            except (OSError, ValueError):
                log.warning("Could not read search memory, it will be rebuilt.")
        return self._search_memory

    def recall_search(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Get the remembered video for a search, if it is still fresh (within
        SearchMemoryDays) and its file is still in the cache.
        """
        days = self.config.search_memory_days
        if not days or days < 0:
            return None
        found = self._load_search_memory().get(self.normalize_search(query))
        if not found:
            return None
        if time.time() - float(found.get("resolved", 0)) > days * 86400:
            return None
        if not self.get_youtube_cached(str(found.get("id", ""))):
            return None
        return found

    def remember_search(
        self, query: str, video_id: str, title: str, duration: Any, url: str
    ) -> None:
        """
        Remember which video a search resolved to, and drop expired memories.
        (Memories whose file was swept are ignored by recall_search and get
        replaced on the next real search.)
        """
        days = self.config.search_memory_days
        if not days or days < 0 or not video_id:
            return
        memory = self._load_search_memory()
        memory[self.normalize_search(query)] = {
            "id": video_id,
            "title": title,
            "duration": duration,
            "url": url,
            "resolved": time.time(),
        }
        cutoff = time.time() - days * 86400
        for key in [k for k, v in memory.items() if float(v.get("resolved", 0)) < cutoff]:
            memory.pop(key)
        try:
            self.ensure_cache_dir_exists()
            path = self.cache_path / AUDIO_CACHE_SEARCH_MEMORY_FILE
            tmp = path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf8") as fh:
                json.dump(memory, fh)
            tmp.replace(path)
        except OSError:
            log.warning("Could not save search memory.", exc_info=True)

    def get_youtube_cached(self, video_id: str) -> str:
        """
        Find a cached YouTube file by video ID alone, for search and playlist
        results whose expected filename isn't known until full extraction.
        Prefers audio-only files over the 403 fallback's .mp4, and ignores
        unfinished downloads.

        :returns: a path string or empty string if not found.
        """
        if not video_id:
            return ""
        matches = [
            item
            for item in self.cache_path.glob(f"youtube-{glob.escape(video_id)}-*")
            if item.is_file() and item.suffix not in (".part", ".ytdl", ".tmp")
        ]
        if not matches:
            return ""
        matches.sort(key=lambda item: item.suffix == ".mp4")
        return str(matches[0])

    def get_if_cached(self, filename: str, ignore_ext: bool = True) -> str:
        """
        Check for an existing cache file by the given name, and return the matched path.
        The `filename` will be reduced to its basename and joined with the current cache_path.
        If `ignore_ext` is set, the filename will be matched without its last suffix / extension.
        An exact match is preferred, but only the first of many possible matches will be returned.

        :returns: a path string or empty string if not found.
        """
        file_path = pathlib.Path(filename)
        filename = file_path.name
        cache_file_path = self.cache_path / filename

        if ignore_ext:
            if cache_file_path.is_file():
                return str(cache_file_path)

            safe_stem = glob.escape(pathlib.Path(filename).stem)
            for item in self.cache_path.glob(f"{safe_stem}.*"):
                if item.is_file():
                    return str(item)

        elif cache_file_path.is_file():
            return str(cache_file_path)

        return ""

    def ensure_cache_dir_exists(self) -> None:
        """Check for and create the cache directory path or raise an error"""
        if not self.cache_dir_exists():
            self.cache_path.mkdir(parents=True)

    def cache_dir_exists(self) -> bool:
        """Wrapper for self.cache.is_dir() for external use."""
        return self.cache_path.is_dir()

    def get_cache_size(self) -> Tuple[int, int]:
        """
        Returns AudioFileCache size as a two member tuple containing size_bytes and file_count.
        """
        return (self.size_bytes, self.file_count)

    def scan_audio_cache(self) -> Tuple[int, int]:
        """
        Scan the audio cache directory and return a tuple with info.
        Returns (size_in_bytes:int, number_of_files:int)
        """
        cached_bytes = 0
        cached_files = 0
        if os.path.isdir(self.cache_path):
            for cache_file in pathlib.Path(self.cache_path).iterdir():
                cached_files += 1
                cached_bytes += os.path.getsize(cache_file)
        self.size_bytes = cached_bytes
        self.file_count = cached_files

        return self.get_cache_size()

    def _delete_cache_file(self, path: pathlib.Path) -> bool:
        """
        Wrapper for pathlib unlink(missing_ok=True) while logging exceptions.
        """
        try:
            path.unlink(missing_ok=True)
            return True
        except (OSError, PermissionError, IsADirectoryError):
            log.warning("Failed to delete cache file:  %s", path, exc_info=True)
            return False

    def _delete_cache_dir(self) -> bool:
        """
        Attempts immediate removal of the cache file directory while logging errors.
        """
        try:
            shutil.rmtree(self.cache_path)
            self.size_bytes = 0
            self.file_count = 0
            log.debug("Audio cache directory has been removed.")
            return True
        except (OSError, PermissionError, NotADirectoryError):
            new_name = self.cache_path.parent.joinpath(self.cache_path.stem + "__")
            try:
                new_path = self.cache_path.rename(new_name)
            except (OSError, PermissionError, FileExistsError):
                log.debug("Audio cache directory could not be removed or renamed.")
                return False
            try:
                shutil.rmtree(new_path)
                return True
            except (OSError, PermissionError, NotADirectoryError):
                new_path.rename(self.cache_path)
                log.debug("Audio cache directory could not be removed.")
                return False

    def _protected_filenames(self) -> set:
        """Basenames of files that are playing or queued in any player."""
        names = set()
        for player in getattr(self.bot, "players", {}).values():
            entries = list(player.playlist.entries)
            if player.current_entry:
                entries.append(player.current_entry)
            for entry in entries:
                for name in (
                    getattr(entry, "filename", ""),
                    getattr(entry, "expected_filename", ""),
                ):
                    if name:
                        names.add(pathlib.Path(name).name)
        return names

    def _sweep_by_score(self) -> bool:
        """
        Smakbot: when the cache is over StorageLimitBytes, delete files in order
        of `keep_until` (last play, plus a bonus for play count) until it is at
        CACHE_SWEEP_TARGET_RATIO of the limit. Files playing or queued, recent
        unplayed downloads, and retained autoplaylist files are never deleted.
        """
        limit = self.config.storage_limit_bytes
        files = [
            item
            for item in self.cache_path.iterdir()
            if item.is_file()
            and not item.name.startswith(".")
            and item.suffix not in (".part", ".ytdl", ".tmp")
        ]
        total = sum(os.path.getsize(item) for item in files)
        if total <= limit:
            self.scan_audio_cache()
            return True

        target = int(limit * CACHE_SWEEP_TARGET_RATIO)
        protected = self._protected_filenames()
        now = time.time()
        candidates = []
        for item in files:
            entry = self._index_entry(item.name)
            if item.name in protected or self._check_autoplay_cachemap(item):
                continue
            if not entry["plays"] and now - entry["created"] < CACHE_NEW_FILE_GRACE_SECONDS:
                continue
            candidates.append((self.keep_until(item.name), item, entry))
        candidates.sort(key=lambda c: c[0])

        removed_count = 0
        removed_size = 0
        for keep, item, entry in candidates:
            if total <= target:
                break
            size = os.path.getsize(item)
            if not self._delete_cache_file(item):
                continue
            total -= size
            removed_count += 1
            removed_size += size
            self._load_index().pop(item.name, None)
            log.info(
                "Cache sweep removed:  %(name)s  (%(plays)d plays, last %(last)s, kept until %(keep)s)",
                {
                    "name": item.name,
                    "plays": int(entry["plays"]),
                    "last": time.strftime("%Y-%m-%d", time.localtime(entry["last_played"])),
                    "keep": time.strftime("%Y-%m-%d", time.localtime(keep)),
                },
            )

        # forget index entries for files that no longer exist.
        names = {item.name for item in self.cache_path.iterdir()}
        for name in [n for n in self._load_index() if n not in names]:
            self._load_index().pop(name)
        self._save_index()

        log.info(
            "Cache sweep removed %(count)d files (%(size)s), cache is now %(now)s of %(limit)s.",
            {
                "count": removed_count,
                "size": format_size_from_bytes(removed_size),
                "now": format_size_from_bytes(total),
                "limit": format_size_from_bytes(limit),
            },
        )
        self.scan_audio_cache()
        return True

    def _process_cache_delete(self) -> bool:
        """
        Sorts cache by access or creation time and deletes any that are older than set limits.
        Will retain cached autoplaylist if enabled and files are in the cachemap.
        """
        if self.config.storage_limit_bytes == 0 and self.config.storage_limit_days == 0:
            log.debug("Audio cache has no limits set, nothing to delete.")
            return False

        # Smakbot: a size limit uses the weighted sweep instead of access times.
        if self.config.storage_limit_bytes:
            return self._sweep_by_score()

        if os.name == "nt":
            # On Windows, creation time (ctime) is the only reliable way to do this.
            # mtime is usually older than download time. atime is changed on multiple files by some part of the player.
            # To make this consistent everywhere, we need to store last-played times for songs on our own.
            cached_files = sorted(
                self.cache_path.iterdir(),
                key=os.path.getctime,
                reverse=True,
            )
        else:
            cached_files = sorted(
                self.cache_path.iterdir(),
                key=os.path.getatime,
                reverse=True,
            )

        max_age = time.time() - (86400 * self.config.storage_limit_days)
        cached_size = 0
        removed_count = 0
        removed_size = 0
        retained_count = 0
        retained_size = 0
        # Accumulate file sizes until a set limit is reached and purge remaining files.
        for cache_file in cached_files:
            file_size = os.path.getsize(cache_file)

            # Do not purge files from autoplaylist if retention is enabled.
            if self._check_autoplay_cachemap(cache_file):
                retained_count += 1
                retained_size += file_size
                cached_size += file_size
                continue

            # get file access/creation time.
            if os.name == "nt":
                file_time = os.path.getctime(cache_file)
            else:
                file_time = os.path.getatime(cache_file)

            # enforce size limit before time limit.
            if (
                self.config.storage_limit_bytes
                and self.config.storage_limit_bytes < cached_size
            ):
                self._delete_cache_file(cache_file)
                removed_count += 1
                removed_size += file_size
                continue

            if self.config.storage_limit_days:
                if file_time < max_age:
                    self._delete_cache_file(cache_file)
                    removed_count += 1
                    removed_size += file_size
                    continue

            cached_size += file_size

        if removed_count:
            log.debug(
                "Audio cache deleted %(number)s file(s), total of %(size)s removed.",
                {
                    "number": removed_count,
                    "size": format_size_from_bytes(removed_size),
                },
            )
        if retained_count:
            log.debug(
                "Audio cached retained %(number)s file(s) from autoplaylist, total of %(size)s retained.",
                {
                    "number": retained_count,
                    "size": format_size_from_bytes(retained_size),
                },
            )
        self.file_count = len(cached_files) - removed_count
        self.size_bytes = cached_size
        log.debug(
            "Audio cache is now %(size)s over %(number)s file(s).",
            {
                "size": format_size_from_bytes(self.size_bytes),
                "number": self.file_count,
            },
        )
        return True

    def delete_old_audiocache(self, remove_dir: bool = False) -> bool:
        """
        Handle deletion of cache data according to settings and return bool status.
        Will return False if no cache directory exists, and error prevented deletion.
        Parameter `remove_dir` is intended only to be used in bot-startup.
        """

        if not os.path.isdir(self.cache_path):
            log.debug("Audio cache directory is missing, nothing to delete.")
            return False

        if self.config.save_videos:
            return self._process_cache_delete()

        if remove_dir:
            return self._delete_cache_dir()

        return True

    def handle_new_cache_entry(self, entry: "URLPlaylistEntry") -> None:
        """
        Test given entry for cachemap inclusion and run cache limit checks.
        """
        if entry.url in self.bot.playlist_mgr.loaded_tracks:
            # ignore partial downloads
            if entry.cache_busted:
                log.noise(  # type: ignore[attr-defined]
                    "Audio cache file is from autoplaylist but marked as busted, ignoring it."
                )
            else:
                self.add_autoplay_cachemap_entry(entry)

        if self.config.save_videos:
            if self.config.storage_limit_bytes:
                # TODO: This could be improved with min/max options, preventing calls to clear on each new entry.
                self.size_bytes = self.size_bytes + entry.downloaded_bytes
                if self.size_bytes > self.config.storage_limit_bytes:
                    log.debug(
                        "Cache level requires cleanup. %s",
                        format_size_from_bytes(self.size_bytes),
                    )
                    self.delete_old_audiocache()
            elif self.config.storage_limit_days:
                # Only running time check if it is the only option enabled, cuts down on IO.
                self.delete_old_audiocache()

    def load_autoplay_cachemap(self) -> None:
        """
        Load cachemap json file if it exists and settings are enabled.
        Cachemap file path is generated in Config using the auto playlist file name.
        The cache map is a dict with filename keys for playlist url values.
        Filenames are stored without their extension due to ytdl potentially getting a different format.
        """
        if (
            not self.config.storage_retain_autoplay
            or not self.config.auto_playlist
            or not self.config.save_videos
        ):
            self.auto_playlist_cachemap = {}
            return

        if not self.cachemap_file.is_file():
            log.debug("Auto playlist has no cache map, moving on.")
            self.auto_playlist_cachemap = {}
            return

        with open(self.cachemap_file, "r", encoding="utf8") as fh:
            try:
                self.auto_playlist_cachemap = json.load(fh)
                log.info(
                    "Loaded auto playlist cache map with %s entries.",
                    len(self.auto_playlist_cachemap),
                )
            except json.JSONDecodeError:
                log.exception("Failed to load auto playlist cache map.")
                self.auto_playlist_cachemap = {}

    async def save_autoplay_cachemap(self) -> None:
        """
        Uses asyncio.Lock to save cachemap as a json file, if settings are enabled.
        """
        if (
            not self.config.storage_retain_autoplay
            or not self.config.auto_playlist
            or not self.config.save_videos
        ):
            return

        if self.cachemap_defer_write:
            log.everything(  # type: ignore[attr-defined]
                "Cachemap defer flag is set, not yet saving to disk..."
            )
            return

        async with self.cachemap_file_lock:
            try:
                with open(self.cachemap_file, "w", encoding="utf8") as fh:
                    json.dump(self.auto_playlist_cachemap, fh)
                    log.debug(
                        "Saved auto playlist cache map with %s entries.",
                        len(self.auto_playlist_cachemap),
                    )
            except (TypeError, ValueError, RecursionError):
                log.exception("Failed to save auto playlist cache map.")

    def add_autoplay_cachemap_entry(self, entry: "BasePlaylistEntry") -> None:
        """
        Store an entry in autoplaylist cachemap, and update the cachemap file if needed.
        """
        if (
            not self.config.storage_retain_autoplay
            or not self.config.auto_playlist
            or not self.config.save_videos
        ):
            return

        change_made = False
        filename = pathlib.Path(entry.filename).stem
        if filename in self.auto_playlist_cachemap:
            if self.auto_playlist_cachemap[filename] != entry.url:
                log.warning(
                    "Auto playlist cache map conflict on Key: %(file)s  Old: %(old)s  New: %(new)s",
                    {
                        "file": filename,
                        "old": self.auto_playlist_cachemap[filename],
                        "new": entry.url,
                    },
                )
                self.auto_playlist_cachemap[filename] = entry.url
                change_made = True
        else:
            self.auto_playlist_cachemap[filename] = entry.url
            change_made = True

        if change_made and not self.cachemap_defer_write:
            self.bot.create_task(
                self.save_autoplay_cachemap(), name="MB_SaveAutoPlayCachemap"
            )

    def remove_autoplay_cachemap_entry(self, entry: "BasePlaylistEntry") -> None:
        """
        Remove an entry from cachemap and update cachemap file if needed.
        """
        if (
            not self.config.storage_retain_autoplay
            or not self.config.auto_playlist
            or not self.config.save_videos
        ):
            return

        filename = pathlib.Path(entry.filename).stem
        if filename in self.auto_playlist_cachemap:
            del self.auto_playlist_cachemap[filename]
            if not self.cachemap_defer_write:
                self.bot.create_task(
                    self.save_autoplay_cachemap(), name="MB_SaveAutoPlayCachemap"
                )

    def remove_autoplay_cachemap_entry_by_url(self, url: str) -> None:
        """
        Remove all entries having the given URL from cachemap and update cachemap if needed.
        """
        if (
            not self.config.storage_retain_autoplay
            or not self.config.auto_playlist
            or not self.config.save_videos
        ):
            return

        to_remove = set()
        for map_key, map_url in self.auto_playlist_cachemap.items():
            if map_url == url:
                to_remove.add(map_key)

        for key in to_remove:
            del self.auto_playlist_cachemap[key]

        if len(to_remove) != 0 and not self.cachemap_defer_write:
            self.bot.create_task(
                self.save_autoplay_cachemap(), name="MB_SaveAutoPlayCachemap"
            )

    def _check_autoplay_cachemap(self, filename: pathlib.Path) -> bool:
        """
        Test if filename is a valid autoplaylist file still.
        Returns True if map entry URL is still in autoplaylist.
        If settings are disabled for cache retention this will also return false.
        """
        if (
            not self.config.storage_retain_autoplay
            or not self.config.auto_playlist
            or not self.config.save_videos
        ):
            return False

        if filename.stem in self.auto_playlist_cachemap:
            cached_url = self.auto_playlist_cachemap[filename.stem]
            if cached_url in self.bot.playlist_mgr.loaded_tracks:
                return True

        return False
