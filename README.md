# smakbot

Smakbot is a Docker-based music bot that joins your Discord voice channel and plays music from a variety of sources. It is derived from [Just-Some-Bots/MusicBot](https://github.com/Just-Some-Bots/MusicBot); see that project's documentation for every config option.

Differences from upstream:

- Debian-based image with [deno](https://deno.com) and the [bgutil PO token provider](https://github.com/Brainicism/bgutil-ytdlp-pot-provider), so yt-dlp can play YouTube without 403s.
- Downloads audio-only streams (Opus, ~130 kbps) instead of 360p video, and falls back to the older YouTube clients if a download gets a 403.
- Loudness normalization: every track gets one fixed gain to reach -14 LUFS (`UseLoudnessNormalization`, `LoudnessNormalizationTarget`). There's no compression, and boosts are capped so peaks never clip.
- Settings that differ from upstream's examples:
  - `config/options.ini`:
    - A single skip vote skips a song (`SkipsRequired = 1`, `SkipRatio = 0`).
    - The queue is not kept across restarts (`PersistentQueue = no`).
    - The autoplaylist is off (`UseAutoPlaylist = no`). If you turn it on, a song someone requests interrupts the current autoplaylist song (`AutoPlaylistAutoSkip = yes`).
    - Default volume is 24% (`DefaultVolume = 0.24`).
    - The bot leaves an empty voice channel after 20 seconds (`LeaveInactiveVCTimeOut = 0:00:20`).
    - `BotExceptionIDs` lists one other bot, by ID, that the bot will respond to.
  - `config/permissions.ini`: no song length limit for regular users (`MaxSongLength = 0`).

## Getting started

1. Clone the repo

   ```bash
   git clone https://github.com/smakus/smakbot-discord-music-bot.git
   cd smakbot-discord-music-bot
   ```

2. Set your bot token in a `.env` file (git-ignored, never baked into the image)

   ```bash
   echo "MUSICBOT_TOKEN=your-discord-bot-token-here" > .env
   ```

3. Build and run

   ```bash
   docker compose up --build -d
   ```

Leave `Token` blank in `config/options.ini`; the bot falls back to `MUSICBOT_TOKEN`. (Setting `Token` in `options.ini` still works and takes priority, but that file is tracked in git, so the token could be committed by accident.)

The owner is detected automatically from the bot application (`OwnerID = 0`), and commands use the `!` prefix (for example `!play <song or URL>`, `!help`).

## Pulling in upstream fixes

```bash
git remote add upstream https://github.com/Just-Some-Bots/MusicBot.git
git fetch upstream
git merge upstream/dev
```
