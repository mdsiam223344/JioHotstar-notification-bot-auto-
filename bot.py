import os
import logging
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes,
    MessageHandler, ConversationHandler, filters
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "8535271767:AAGASCq-ncUEGY5IYnszNs_WOGQ8xlewOoY").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "1686274364"))
CHANNEL_USERNAME = os.getenv("FORCE_JOIN_CHANNEL", "-1004427032466").strip()
DB_PATH = os.getenv("DB_PATH", "episodes.db")
TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Dhaka"))
POLL_MINUTES = max(30, int(os.getenv("POLL_MINUTES", "180")))
# Add TVmaze show IDs for shows available in its catalog, comma-separated.
# Example: TVMAZE_SHOW_IDS=1,82,123
TVMAZE_SHOW_IDS = [x.strip() for x in os.getenv("TVMAZE_SHOW_IDS", "").split(",") if x.strip().isdigit()]
# Map a TVmaze show name to the official JioHotstar title/watch page when known.
# This bot never scrapes JioHotstar; official links are supplied by the admin.
SHOW_LINKS = {
    x.strip().lower(): y.strip()
    for x, y in (item.split("=", 1) for item in os.getenv("OFFICIAL_SHOW_LINKS", "").split(";;") if "=" in item)
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("jiohotstar-bot")
SHOW, SEASON, EPISODE, TITLE, DATE, POSTER, LINK = range(7)
TVMAZE_BASE = "https://api.tvmaze.com"


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS subscribers (
            user_id INTEGER PRIMARY KEY, joined_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL DEFAULT 'admin',
            source_episode_id TEXT UNIQUE,
            show_name TEXT NOT NULL, season TEXT, episode TEXT NOT NULL,
            title TEXT, release_date TEXT, poster_url TEXT, official_link TEXT,
            sent INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS tracked_shows (
            tvmaze_id INTEGER PRIMARY KEY, show_name TEXT NOT NULL, added_at TEXT NOT NULL
        )""")


def is_admin(uid):
    return ADMIN_ID != 0 and uid == ADMIN_ID


async def joined(context, uid):
    if not CHANNEL_USERNAME:
        return True
    try:
        m = await context.bot.get_chat_member(CHANNEL_USERNAME, uid)
        return m.status in ("member", "administrator", "creator")
    except Exception:
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    with db() as c:
        c.execute("INSERT OR IGNORE INTO subscribers VALUES (?, ?)", (u.id, datetime.now(TZ).isoformat()))
    if not await joined(context, u.id):
        kb = [[InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}")],
              [InlineKeyboardButton("✅ I've Joined", callback_data="check_join")]]
        await update.message.reply_text("বট ব্যবহার করতে আগে চ্যানেলে যোগ দিন।", reply_markup=InlineKeyboardMarkup(kb))
        return
    await update.message.reply_text(
        "🎬 JioHotstar Episode Notification Bot\n\n"
        "নতুন এপিসোডের তথ্য অনুমোদিত TVmaze API-তে পাওয়া গেলে স্বয়ংক্রিয় নোটিফিকেশন আসবে। "
        "এটি JioHotstar-এর নিজস্ব API নয়; তাই সব ভারতীয় সিরিয়াল বা Hotstar রিলিজের তথ্য নাও থাকতে পারে।\n\n"
        "/latest — সর্বশেষ নোটিফিকেশন\n/help — সাহায্য"
    )


async def check_join(update, context):
    q = update.callback_query
    await q.answer()
    if await joined(context, q.from_user.id):
        await q.edit_message_text("✅ যোগদান যাচাই হয়েছে। /start লিখুন।")
    else:
        await q.answer("আগে চ্যানেলে যোগ দিন।", show_alert=True)


async def help_cmd(update, context):
    await update.message.reply_text(
        "/start — চালু\n/latest — সর্বশেষ এপিসোড\n/help — সাহায্য\n\n"
        "Admin:\n/add_episode — হাতে এপিসোড যোগ\n"
        "/track_show TVMAZE_ID — TVmaze-এ থাকা শো ট্র্যাক\n"
        "/untrack_show TVMAZE_ID — ট্র্যাক বন্ধ\n"
        "/tracked — ট্র্যাক করা শো\n/scan_now — এখনই API scan\n"
        "/notify ID — নির্দিষ্ট এপিসোডের নোটিফিকেশন\n/episodes — সর্বশেষ এপিসোড\n/stats — পরিসংখ্যান"
    )


def fmt(r):
    season = f" | Season {r['season']}" if r["season"] else ""
    title = f"\n🎞️ {r['title']}" if r["title"] else ""
    date = f"\n📅 Release: {r['release_date']}" if r["release_date"] else ""
    link = f"\n▶️ Official watch: {r['official_link']}" if r["official_link"] else ""
    attribution = "\n📚 Metadata: TVmaze (CC BY-SA)" if r["source"] == "tvmaze" else ""
    return f"🆕 #NewEpisode\n📺 {r['show_name']}{season}\n🔢 Episode: {r['episode']}{title}{date}{link}{attribution}"


async def broadcast(context, row):
    with db() as c:
        users = c.execute("SELECT user_id FROM subscribers").fetchall()
    sent, failed = 0, 0
    msg = fmt(row)
    for u in users:
        try:
            if row["poster_url"]:
                await context.bot.send_photo(u["user_id"], row["poster_url"], caption=msg)
            else:
                await context.bot.send_message(u["user_id"], msg, disable_web_page_preview=False)
            sent += 1
        except Exception as e:
            failed += 1
            log.info("send to %s failed: %s", u["user_id"], e)
    return sent, failed


async def latest(update, context):
    with db() as c:
        rows = c.execute("SELECT * FROM episodes WHERE sent=1 ORDER BY id DESC LIMIT 5").fetchall()
    if not rows:
        await update.message.reply_text("এখনও কোনো এপিসোড নোটিফাই করা হয়নি।")
    for r in rows:
        await update.message.reply_text(fmt(r), disable_web_page_preview=False)


async def track_show(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("ব্যবহার: /track_show TVMAZE_ID\nশোর ID পেতে https://www.tvmaze.com/api দেখুন।")
        return
    sid = int(context.args[0])
    try:
        res = requests.get(f"{TVMAZE_BASE}/shows/{sid}", timeout=20)
        if res.status_code == 404:
            await update.message.reply_text("এই ID-তে শো পাওয়া যায়নি।")
            return
        res.raise_for_status()
        show = res.json()
    except Exception as e:
        await update.message.reply_text(f"TVmaze API error: {e}")
        return
    with db() as c:
        c.execute("INSERT OR REPLACE INTO tracked_shows VALUES (?, ?, ?)", (sid, show.get("name", str(sid)), datetime.now(TZ).isoformat()))
    await update.message.reply_text(f"✅ Tracking enabled:\n{show.get('name')}\nTVmaze ID: {sid}\n\nএখন থেকে API-তে নতুন এপিসোড দেখা গেলে বট নোটিফিকেশন পাঠাবে।")


async def untrack_show(update, context):
    if not is_admin(update.effective_user.id):
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("ব্যবহার: /untrack_show TVMAZE_ID")
        return
    with db() as c:
        c.execute("DELETE FROM tracked_shows WHERE tvmaze_id=?", (int(context.args[0]),))
    await update.message.reply_text("Tracking বন্ধ করা হয়েছে।")


async def tracked(update, context):
    if not is_admin(update.effective_user.id):
        return
    with db() as c:
        rows = c.execute("SELECT * FROM tracked_shows ORDER BY show_name").fetchall()
    if not rows:
        await update.message.reply_text("কোনো শো ট্র্যাক করা হচ্ছে না।")
        return
    await update.message.reply_text("📺 Tracked shows:\n" + "\n".join(f"{r['tvmaze_id']} — {r['show_name']}" for r in rows))


def fetch_show_and_episodes(sid):
    show_r = requests.get(f"{TVMAZE_BASE}/shows/{sid}", timeout=20)
    show_r.raise_for_status()
    show = show_r.json()
    eps_r = requests.get(f"{TVMAZE_BASE}/shows/{sid}/episodes", timeout=30)
    eps_r.raise_for_status()
    return show, eps_r.json()


async def scan_tracked(context):
    with db() as c:
        shows = c.execute("SELECT * FROM tracked_shows").fetchall()
    for tracked_show in shows:
        sid = tracked_show["tvmaze_id"]
        try:
            show, eps = fetch_show_and_episodes(sid)
        except Exception:
            log.exception("TVmaze fetch failed for show ID %s", sid)
            continue
        name = show.get("name") or tracked_show["show_name"]
        image = show.get("image") or {}
        poster = (image or {}).get("original") or (image or {}).get("medium") or ""
        for ep in eps:
            ep_id = str(ep.get("id", ""))
            if not ep_id:
                continue
            airdate = ep.get("airdate") or ""
            # Avoid alerting for old catalog entries when first tracking: only recent/upcoming episodes.
            if airdate:
                try:
                    air_day = datetime.strptime(airdate, "%Y-%m-%d").date()
                    if air_day < (datetime.now(TZ).date() - timedelta(days=2)):
                        continue
                except ValueError:
                    pass
            season = str(ep.get("season") or "")
            number = str(ep.get("number") or ep.get("id"))
            official = SHOW_LINKS.get(name.lower(), "")
            with db() as c:
                cur = c.execute(
                    """INSERT OR IGNORE INTO episodes
                    (source, source_episode_id, show_name, season, episode, title, release_date,
                     poster_url, official_link, sent, created_at)
                    VALUES ('tvmaze', ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                    (ep_id, name, season, number, ep.get("name") or "", airdate, poster,
                     official, datetime.now(TZ).isoformat())
                )
                new_id = cur.lastrowid
                inserted = cur.rowcount == 1
                if inserted:
                    row = c.execute("SELECT * FROM episodes WHERE id=?", (new_id,)).fetchone()
                else:
                    row = None
            if inserted and row:
                sent, failed = await broadcast(context, row)
                with db() as c:
                    c.execute("UPDATE episodes SET sent=1 WHERE id=?", (new_id,))
                log.info("Auto notification: %s S%sE%s; sent=%s failed=%s", name, season, number, sent, failed)


async def scheduled_scan(context):
    await scan_tracked(context)


async def scan_now(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    await update.message.reply_text("🔎 TVmaze API scan শুরু হয়েছে...")
    await scan_tracked(context)
    await update.message.reply_text("✅ Scan শেষ। নতুন এপিসোড পাওয়া গেলে নোটিফিকেশন পাঠানো হয়েছে।")


async def add_episode_start(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return ConversationHandler.END
    await update.message.reply_text("সিরিয়ালের নাম লিখুন:")
    return SHOW


async def get_show(update, context):
    context.user_data["show_name"] = update.message.text.strip()
    await update.message.reply_text("Season নম্বর (না থাকলে 0):")
    return SEASON


async def get_season(update, context):
    x = update.message.text.strip()
    context.user_data["season"] = "" if x == "0" else x
    await update.message.reply_text("Episode নম্বর:")
    return EPISODE


async def get_episode(update, context):
    context.user_data["episode"] = update.message.text.strip()
    await update.message.reply_text("Episode title (না থাকলে -):")
    return TITLE


async def get_title(update, context):
    x = update.message.text.strip()
    context.user_data["title"] = "" if x == "-" else x
    await update.message.reply_text("Release date (না থাকলে -):")
    return DATE


async def get_date(update, context):
    x = update.message.text.strip()
    context.user_data["release_date"] = "" if x == "-" else x
    await update.message.reply_text("Poster URL (না থাকলে -):")
    return POSTER


async def get_poster(update, context):
    x = update.message.text.strip()
    context.user_data["poster_url"] = "" if x == "-" else x
    await update.message.reply_text("Official watch URL (না থাকলে -):")
    return LINK


async def get_link(update, context):
    d = context.user_data
    x = update.message.text.strip()
    link = "" if x == "-" else x
    with db() as c:
        cur = c.execute(
            """INSERT INTO episodes(source, show_name, season, episode, title, release_date, poster_url,
            official_link, created_at) VALUES ('admin', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (d["show_name"], d["season"], d["episode"], d["title"], d["release_date"],
             d["poster_url"], link, datetime.now(TZ).isoformat())
        )
        eid = cur.lastrowid
    await update.message.reply_text(f"✅ Saved. Episode ID: {eid}\nUse /notify {eid} to send now.")
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update, context):
    context.user_data.clear()
    await update.message.reply_text("বাতিল করা হয়েছে।")
    return ConversationHandler.END


async def notify_episode(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("ব্যবহার: /notify ID")
        return
    with db() as c:
        row = c.execute("SELECT * FROM episodes WHERE id=?", (int(context.args[0]),)).fetchone()
    if not row:
        await update.message.reply_text("Episode ID পাওয়া যায়নি।")
        return
    sent, failed = await broadcast(context, row)
    with db() as c:
        c.execute("UPDATE episodes SET sent=1 WHERE id=?", (row["id"],))
    await update.message.reply_text(f"✅ Done. Sent: {sent}, Failed: {failed}")


async def episodes(update, context):
    if not is_admin(update.effective_user.id):
        return
    with db() as c:
        rows = c.execute("SELECT id, source, show_name, season, episode, sent FROM episodes ORDER BY id DESC LIMIT 10").fetchall()
    if not rows:
        await update.message.reply_text("এপিসোড নেই।")
        return
    await update.message.reply_text("\n".join(
        f"ID {r['id']} [{r['source']}] {r['show_name']} S{r['season']}E{r['episode']} | sent={r['sent']}" for r in rows
    ))


async def stats(update, context):
    if not is_admin(update.effective_user.id):
        return
    with db() as c:
        u = c.execute("SELECT COUNT(*) n FROM subscribers").fetchone()["n"]
        e = c.execute("SELECT COUNT(*) n FROM episodes").fetchone()["n"]
        s = c.execute("SELECT COUNT(*) n FROM tracked_shows").fetchone()["n"]
    await update.message.reply_text(f"👥 Users: {u}\n🎬 Episodes: {e}\n🔎 Tracked shows: {s}")


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing in .env")
    if not ADMIN_ID:
        raise RuntimeError("ADMIN_ID is missing in .env")
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("add_episode", add_episode_start)],
        states={
            SHOW: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_show)],
            SEASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_season)],
            EPISODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_episode)],
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_title)],
            DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_date)],
            POSTER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_poster)],
            LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_link)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    for h in [
        CommandHandler("start", start), CommandHandler("help", help_cmd),
        CommandHandler("latest", latest), CommandHandler("track_show", track_show),
        CommandHandler("untrack_show", untrack_show), CommandHandler("tracked", tracked),
        CommandHandler("scan_now", scan_now), CommandHandler("notify", notify_episode),
        CommandHandler("episodes", episodes), CommandHandler("stats", stats),
        CallbackQueryHandler(check_join, pattern="^check_join$"), conv
    ]:
        app.add_handler(h)
    app.job_queue.run_repeating(scheduled_scan, interval=POLL_MINUTES * 60, first=20)
    log.info("Bot started; TVmaze scan interval: %s minutes", POLL_MINUTES)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
