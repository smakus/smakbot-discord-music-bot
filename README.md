# smakbot: Self-Hosted Discord Music Bot in Docker

**smakbot** is a free, self-hosted Discord music bot that runs in Docker. It joins your voice channel and plays songs from YouTube, SoundCloud and Bandcamp (and Spotify, with API keys), with even loudness from track to track, a smart local cache, and a "most played" playlist built from what your server actually listens to.

It's a fork of [Just-Some-Bots/MusicBot](https://github.com/Just-Some-Bots/MusicBot), tuned to work out of the box (no YouTube 403 errors) and built to pair with [Luna](https://github.com/smakus/luna-discord-ai-voice-chatbot), a local AI voice assistant: say *"hey Luna, play Bohemian Rhapsody"* and smakbot plays it.

**Contents:** [Features](#features) · [Commands](#commands) · [Using smakbot with Luna](#using-smakbot-with-luna) · [Getting started](#getting-started) · [Configuration](#configuration) · [Now playing API](#now-playing-api) · [Updating from upstream](#pulling-in-upstream-fixes)

## Features

- 🎵 **Plays from YouTube, SoundCloud and Bandcamp**, or a plain search: `!play never gonna give you up`. Spotify links work once `Spotify_ClientID` and `Spotify_ClientSecret` are set in `config/options.ini` (free keys from the [Spotify developer dashboard](https://developer.spotify.com/dashboard)).
- 🔊 **Even volume across songs.** Every track is normalized to -14 LUFS (the same loudness as YouTube) with one fixed gain: no compression, and boosts never clip.
- 🎧 **Audio-only downloads** (Opus, about 130 kbps) instead of video, so songs start faster and the cache holds more.
- ✅ **YouTube that keeps working.** The image includes [deno](https://deno.com) and the [bgutil PO token provider](https://github.com/Brainicism/bgutil-ytdlp-pot-provider), and downloads that hit a 403 retry with other YouTube clients.
- 🏆 **Your server's top songs.** `!playtop` queues the most played songs, straight from the cache.
- 🔁 **`!replay`** plays the last song again.
- 🧠 **Search memory.** Repeating a search plays the same song from the cache without asking YouTube; `!fresh` forces a new search.
- 💾 **A cache that keeps what you like.** It's capped at 3 GB. When it's full, the least recently played songs go first, and every doubling of a song's play count keeps it two weeks longer.
- 🤖 **Works with Luna.** Luna can control it by voice, credit songs to whoever asked, and ask what's playing (see [Using smakbot with Luna](#using-smakbot-with-luna)).
- 🏷️ **Status shows the song and who queued it**, e.g. *"Seal - Crazy · smakus"*.

## Commands

Type these in any text channel the bot can read. The prefix is `!`. `!help` lists everything, and `!help <command>` explains one.

### Playing music

| Command | What it does |
| ------- | ------------ |
| `!play <song name or link>` (`!p`) | Adds a song to the queue, or starts playing if nothing is. A search, a YouTube, SoundCloud or Bandcamp link (Spotify with API keys), or a playlist link |
| `!playnext <song or link>` | Adds it as the next song instead of last |
| `!playnow <song or link>` | Skips the current song and plays this one now |
| `!playtop [count]` (`!top`, `!mostplayed`) | Queues your server's most played songs from the cache, most plays first; 10 if no count |
| `!replay` (`!again`) | Plays the last finished or skipped song again, as the next song |
| `!fresh <search>` | Like `!play`, but always searches YouTube anew, replacing the remembered result. For when a search picked the wrong video |
| `!shuffleplay <playlist link>` | Queues a playlist in shuffled order |
| `!search [yt\|sc] [number] <search>` | Shows a few results to choose from with reactions (YouTube by default; `sc` for SoundCloud) |
| `!stream <link>` | Plays a live stream (Twitch, YouTube live, internet radio) without downloading |

### Controlling playback

| Command | What it does |
| ------- | ------------ |
| `!pause` / `!resume` (`!unpause`, `!continue`) | Pauses or resumes the current song |
| `!skip` (`!s`) | Skips the current song (one vote is enough on this bot) |
| `!seek <seconds>` | Jumps to a point in the song; `+30` or `-15` for relative jumps |
| `!repeat [song\|all\|off]` | Repeats the current song or the whole queue |
| `!volume [1-100]` | Sets the volume, or `+10` / `-10` to adjust. Lasts until the bot restarts |
| `!speed <rate>` | Plays the current song faster or slower (`1.25`, `0.8`) |
| `!summon` (`!join`, `!come`) | Brings the bot into your voice channel |
| `!follow` | Has the bot follow you when you move between voice channels |
| `!disconnect` (`!leave`, `!stop`) | Stops the music and leaves the voice channel |

### The queue

| Command | What it does |
| ------- | ------------ |
| `!queue [page]` (`!q`) | Shows what's coming up |
| `!np` | Shows the song that's playing, how far in it is, and who added it |
| `!shuffle` | Shuffles the queue |
| `!move <from> <to>` | Moves a song to another position (see `!queue` for positions) |
| `!remove [position]` | Removes a song, a range (`!remove 3 6`) or everything someone added (`!remove @name`) |
| `!clear` | Empties the queue but keeps the current song playing |

### Other

| Command | What it does |
| ------- | ------------ |
| `!help [command]` | Lists the commands, or explains one |
| `!perms` | Shows what you're allowed to do |
| `!id [@user]` | Shows a Discord user ID |
| `!karaoke` | Karaoke mode: only karaoke members can queue songs |

What each person may do is set in `config/permissions.ini`. By default everyone can play and skip, up to 8 songs each in the queue, but can't remove other people's songs. Settings and server-management commands (`!config`, `!setperms`, `!restart`, …) are for the bot's owner.

## Using smakbot with Luna

[Luna](https://github.com/smakus/luna-discord-ai-voice-chatbot) is a local AI voice assistant for Discord. She relays music requests to smakbot as ordinary text commands, so everything above also works by voice:

| Say to Luna | She sends |
| ----------- | --------- |
| "Hey Luna, play Bohemian Rhapsody" | `!summon` (if smakbot isn't in the channel yet), then `!play Bohemian Rhapsody` |
| "Hey Luna, play the top 10" / "play our most played" | `!playtop 10` |
| "Hey Luna, skip" | `!skip` |
| "Hey Luna, stop the music" | `!stop` (smakbot stops and leaves) |
| "Hey Luna, put on something chill" | Her LLM picks a search and sends `!play …` |
| "Hey Luna, what song is this?" | Nothing: she asks smakbot's [now playing API](#now-playing-api) and answers out loud |
| "Hey Luna, what are our top songs?" | Nothing: she reads the most played list from `/top-songs` without playing it |

What happens between the two bots:

- **Luna is allowed to send commands.** smakbot ignores other bots, except the ones listed in `BotExceptionIDs` in `config/options.ini`. Put Luna's user ID there.
- **Songs are credited to the person who asked, not to Luna.** Luna ends the command with a mention of whoever asked, e.g. `!play Bohemian Rhapsody --for=@smakus`. She sends it without pinging them. smakbot then shows that person as the one who added the song: in "Now playing", `!np`, the status, and the now playing API. This only changes the credit: the command still runs as Luna, with Luna's permissions. From anyone else, `--for` means nothing.
- **Luna knows what's playing.** She reads `/now-playing` (see below), so you can ask her about the song: *"what's this song about?"*, *"when did it come out?"*
- **Give Luna a permission group** without the per-person limits, since everyone's requests arrive as hers. In `config/permissions.ini`:

  ```ini
  [LunaBot]
  UserList = <Luna's Discord user ID>
  MaxSongs = 0
  MaxSongLength = 0
  MaxPlaylistLength = 0
  AllowPlaylists = yes
  ```

## Getting started

You need Docker and a Discord bot token ([Discord Developer Portal](https://discord.com/developers/applications) → New Application → Bot). Enable the **Message Content Intent**, and invite the bot with permission to read and send messages, connect and speak.

1. Clone the repo:

   ```bash
   git clone https://github.com/smakus/smakbot-discord-music-bot.git
   cd smakbot-discord-music-bot
   ```

2. Put your bot token in a `.env` file. It's git-ignored and never baked into the image:

   ```bash
   echo "MUSICBOT_TOKEN=your-discord-bot-token-here" > .env
   ```

3. Build and start it:

   ```bash
   docker compose up --build -d
   ```

Then join a voice channel and type `!play` with a song. Leave `Token` blank in `config/options.ini`, so the bot uses `MUSICBOT_TOKEN`. Setting `Token` there also works and takes priority, but that file is tracked in git, so a token there could be committed by accident. The owner is detected automatically from the bot application (`OwnerID = 0`).

## Configuration

Settings live in `config/options.ini` and `config/permissions.ini`; [MusicBot's documentation](https://just-some-bots.github.io/MusicBot/) covers every option. Restart the bot after changing them (`docker compose restart musicbot`). What this fork adds or sets differently:

| Setting | Here | What it does |
| ------- | ---- | ------------ |
| `UseLoudnessNormalization` / `LoudnessNormalizationTarget` | on / `-14` | One fixed gain per track to reach -14 LUFS. Higher (e.g. -12) is louder for every song; for a louder bot overall, raise `DefaultVolume` instead |
| `DefaultVolume` | `0.24` | Starting volume (24%) |
| `StorageLimitBytes` | `3 GB` | Cache cap. Over it, the cache is swept to 90%: least recently played first, and each doubling of a song's play count keeps it 14 days longer (a play counts after 30 seconds). Playing, queued and new songs are kept. Play stats are in `audio_cache/.cache_index.json` |
| `SearchMemoryDays` | `30` | How long a search remembers which song it found. `0` turns it off |
| `StatusApiPort` | `8896` | The [now playing API](#now-playing-api). `0` turns it off |
| `StatusMessage` | empty | Empty shows *"<title> · <who queued it>"*. A custom one can use `{p0_title}`, `{p0_author}`, `{p0_length}`, `{p0_url}` |
| `BotExceptionIDs` | Luna's ID | Bots the bot will take commands from (see [Using smakbot with Luna](#using-smakbot-with-luna)) |
| `SkipsRequired` / `SkipRatio` | `1` / `0` | One `!skip` is enough |
| `PersistentQueue` | `no` | The queue isn't kept across restarts |
| `UseAutoPlaylist` | `no` | No background playlist. If you turn it on, a song someone asks for interrupts the autoplaylist song (`AutoPlaylistAutoSkip = yes`) |
| `LeaveInactiveVCTimeOut` | `0:00:20` | Leaves an empty voice channel after 20 seconds |
| `MaxSongLength` (`permissions.ini`) | `0` | No song length limit for regular users |

## Now playing API

With `StatusApiPort` set, smakbot answers `GET http://localhost:8896/now-playing` with what it's playing. Add `?guild=<server id>` if it's in more than one server.

```json
{
  "playing": true,
  "paused": false,
  "title": "Seal - Crazy (Official Music Video)",
  "artist": "Seal",
  "track": "Crazy",
  "uploader": "Seal",
  "url": "https://www.youtube.com/watch?v=4Fc67yQsPqQ",
  "requested_by": "smakus",
  "elapsed": 73.2,
  "duration": 212.0,
  "voice_channel": "Talk Soup",
  "up_next": ["Kiss From a Rose", "Prayer for the Dying"]
}
```

When nothing is playing, it answers `{"playing": false}`. `artist` and `track` appear when YouTube provides them.

`GET http://localhost:8896/top-songs?count=5` lists the most played songs, the same list `!playtop` queues (`count` 1–50, default 10):

```json
{"songs": [{"title": "Shock My Dog I Can't Stop", "plays": 9}, {"title": "Peter Gabriel - Shock The Monkey", "plays": 3}]}
```

Both endpoints are read-only and have no password, so `docker-compose.yml` publishes the port on `127.0.0.1` only. Other containers on the same machine reach it at `host.docker.internal:8896`.

## Pulling in upstream fixes

```bash
git remote add upstream https://github.com/Just-Some-Bots/MusicBot.git
git fetch upstream
git merge upstream/dev
```

## License

MIT, like [MusicBot](https://github.com/Just-Some-Bots/MusicBot), which smakbot is built on. See [LICENSE](LICENSE).
