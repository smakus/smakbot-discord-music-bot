# smakbot

Smakbot is a docker-based music bot that will join your discord audio channel and play music from a variety of sources.  Peruse the config files for all options, and read documentation from the original repo:  https://github.com/Just-Some-Bots/MusicBot

## Getting started

1. Clone the repo

   ```bash
   git clone https://github.com/smakus/smakbot.git
   cd smakbot
   ```

2. Set your bot token

   Open `config/options.ini` and set:

   ```ini
   Token = your-discord-bot-token-here
   ```

3. Run it

   ```bash
   docker compose up -d
   ```

That's it — the bot will start and connect using the token from `config/options.ini`.
