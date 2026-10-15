# smakbot

Smakbot is a Docker-based music bot that joins your Discord voice channel and plays music from a variety of sources. It is derived from [Just-Some-Bots/MusicBot](https://github.com/Just-Some-Bots/MusicBot); see that project's documentation for every config option.

Differences from upstream:

- Debian-based image with [deno](https://deno.com) and the [bgutil PO token provider](https://github.com/Brainicism/bgutil-ytdlp-pot-provider), so yt-dlp can play YouTube without 403s.
- Tuned defaults in `config/options.ini` (lower skip requirements, persistent queue, autoplaylist on, etc.).

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

Leave `Token` blank in `config/options.ini`; the bot falls back to `MUSICBOT_TOKEN`.

## Pulling in upstream fixes

```bash
git remote add upstream https://github.com/Just-Some-Bots/MusicBot.git
git fetch upstream
git merge upstream/dev
```
