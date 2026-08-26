# smakbot

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
