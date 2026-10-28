# JioHotstar Notification Bot — Auto Detection (TVmaze)

This version periodically checks the public TVmaze API for tracked shows and automatically notifies Telegram subscribers about newly listed episodes. TVmaze is an independent third-party metadata source, **not JioHotstar's own API**. It cannot guarantee coverage of Indian serials or confirm that an episode is newly available on JioHotstar. Official watch links are optional admin-provided links.

TVmaze API docs: https://www.tvmaze.com/api
TVmaze attribution is included in automated notification text. TVmaze data is licensed CC BY-SA; follow the license terms.

## Android Termux
1. Extract ZIP and open Termux.
2. Install Python:
   `pkg update && pkg upgrade -y && pkg install python -y`
3. `cd` into the extracted folder.
4. Install dependencies: `pip install -r requirements.txt`
5. `cp .env.example .env && nano .env`
6. Add your Telegram Bot Token from @BotFather and your numeric Telegram user ID as ADMIN_ID.
7. Run: `python bot.py`

## Automatic tracking
1. Start your bot and send `/start`.
2. As admin, find a show's numeric TVmaze ID at https://www.tvmaze.com/api or use TVmaze search on its site.
3. Send `/track_show ID` to the bot.
4. The bot checks tracked shows every 180 minutes by default (`POLL_MINUTES` can be changed; minimum 30 minutes).
5. Use `/scan_now` to test immediately, `/tracked` to view tracked shows, `/untrack_show ID` to stop tracking.

## Admin manual fallback
Use `/add_episode`, answer each question, then use `/notify ID` to send the episode manually.

## Official JioHotstar link mapping
Optional `.env` setting:
`OFFICIAL_SHOW_LINKS=Exact TVmaze Show Name=https://www.hotstar.com/your-official-title-page`
For multiple entries separate them with `;;`. Only use real official links; the bot does not guess or scrape them.

## Render
Deploy as a **Background Worker** with build command `pip install -r requirements.txt` and start command `python bot.py`. Set BOT_TOKEN and ADMIN_ID in environment variables. Configure persistent disk/external DB if you need SQLite data to survive restarts/redeploys.

## Important limitations
- TVmaze catalog/schedule is incomplete for many Indian serials and does not reliably indicate JioHotstar availability.
- New episode metadata can appear with a delay; API responses are cached.
- This is metadata-based detection, not direct monitoring of the JioHotstar app/site.
- Telegram users must start the bot before the bot can DM them.
- Keep `.env` and your bot token private.
