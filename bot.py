import asyncio
import time
import aiohttp
import os

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

TOKEN = os.environ.get("BOT_TOKEN")

# ─────────────────────────────────────────
#  CROP DEFINITIONS
# ─────────────────────────────────────────
CROP_MAP = {
    0:  ("cactus",     "🌵 Cactus"),
    1:  ("carrot",     "🥕 Carrot"),
    2:  ("cocoa",      "🌰 Cocoa Beans"),
    3:  ("melon",      "🍉 Melon"),
    4:  ("mushroom",   "🍄 Mushroom"),
    5:  ("netherwart", "🌌 Nether Wart"),
    6:  ("potato",     "🥔 Potato"),
    7:  ("pumpkin",    "🎃 Pumpkin"),
    8:  ("sugarcane",  "🎋 Sugar Cane"),
    9:  ("wheat",      "🌾 Wheat"),
    10: ("sunflower",  "🌻 Sunflower"),
    11: ("moonflower", "🌸 Moonflower"),
    12: ("wildrose",   "🌹 Wild Rose"),
}

KEY_TO_CODE  = {v[0]: k for k, v in CROP_MAP.items()}
KEY_TO_LABEL = {v[0]: v[1] for v in CROP_MAP.values()}
ALL_KEYS     = list(KEY_TO_CODE.keys())

MAX_CROPS = 3
API_URL   = "https://jacobs.strassburger.dev/api/jacobcontests"

# ─────────────────────────────────────────
#  STATE
# ─────────────────────────────────────────
user_data   = {}
sent_alerts = set()


# ─────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────
def get_user(user_id: int) -> dict:
    user_data.setdefault(user_id, {"fav_all": False, "list": []})
    return user_data[user_id]


def label(key: str) -> str:
    return KEY_TO_LABEL.get(key, key)


def minutes_until(ts_ms: int) -> float:
    return (ts_ms - time.time() * 1000) / 60_000


# ─────────────────────────────────────────
#  KEYBOARDS
# ─────────────────────────────────────────
def main_menu(fav_all: bool = False) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Next Contests", callback_data="next")],
        [InlineKeyboardButton("⭐ My Favorites",  callback_data="fav")],
        [InlineKeyboardButton("➕ Add Crop",       callback_data="add")],
        [InlineKeyboardButton("➖ Remove Crop",    callback_data="remove")],
        [InlineKeyboardButton(
            "⭐🔥 Fav All  (ALL alerts ON)" if fav_all else "⭐ Fav All",
            callback_data="favall"
        )],
        [InlineKeyboardButton("🔕 Clear All",      callback_data="clearall")],
    ])


def crop_keyboard(prefix: str, keys: list) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(label(k), callback_data=f"{prefix}{k}")] for k in keys]
    buttons.append([InlineKeyboardButton("« Back", callback_data="back")])
    return InlineKeyboardMarkup(buttons)


# ─────────────────────────────────────────
#  API
# ─────────────────────────────────────────
async def fetch_contests() -> list:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(API_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json(content_type=None)

        now_ms = time.time() * 1000
        upcoming = []

        for contest in data:
            ts = contest.get("timestamp") or contest.get("time") or contest.get("start")
            if not ts or ts <= now_ms:
                continue

            crops_raw = contest.get("crops", [])
            crop_codes = []

            for c in crops_raw:
                if isinstance(c, int):
                    crop_codes.append(c)
                elif isinstance(c, dict):
                    crop_codes.append(c.get("id", c.get("crop", -1)))

            crop_keys = [
                CROP_MAP[code][0]
                for code in crop_codes
                if code in CROP_MAP
            ]

            upcoming.append({"timestamp": ts, "crops": crop_keys})

        upcoming.sort(key=lambda x: x["timestamp"])
        return upcoming

    except Exception as e:
        print(f"[API error] {e}")
        return []


# ─────────────────────────────────────────
#  NEXT CONTEXT (NEW)
# ─────────────────────────────────────────
async def show_next(update, context, edit=False, query=None):
    contests = await fetch_contests()

    if not contests:
        msg = "⚠️ Couldn't fetch data right now. Try again later."
        if edit:
            await query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return

    lines = ["📅 *Upcoming Contests:*\n"]

    for c in contests[:6]:
        mins = minutes_until(c["timestamp"])
        crop_text = "  ".join(label(k) for k in c["crops"])

        if mins < 60:
            time_str = f"in {int(mins)}m"
        else:
            time_str = f"in {int(mins // 60)}h {int(mins % 60)}m"

        lines.append(f"{crop_text}\n_starts {time_str}_\n")

    text = "\n".join(lines)

    if edit:
        await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=main_menu(data["fav_all"])
        )
    else:
        await update.message.reply_text(text, parse_mode="Markdown")


# ─────────────────────────────────────────
#  COMMANDS
# ─────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = get_user(update.effective_user.id)
    await update.message.reply_text(
        "🌾 *Jacob's Farming Contest Bot*\n\n"
        "Get notified 10 minutes before your favourite crops contest.\n\n"
        "_Data by_ jacobs.strassburger.dev",
        parse_mode="Markdown",
        reply_markup=main_menu(data["fav_all"]),
    )


async def test_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧪 Sending a test alert in 2 seconds…")
    await asyncio.sleep(2)
    await update.message.reply_text("🚨 Test alert!")


async def next_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_next(update, context, edit=False)


# ─────────────────────────────────────────
#  BUTTON HANDLER
# ─────────────────────────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = get_user(user_id)
    action = query.data

    if action == "next":
        await show_next(update, context, edit=True, query=query)

    elif action == "back":
        await query.edit_message_text(
            "🌾 *Jacob's Farming Contest Bot*\nChoose an option:",
            parse_mode="Markdown",
            reply_markup=main_menu(data["fav_all"]),
        )

    elif action == "fav":
        crops = data["list"]
        text = (
            "⭐ *Your Favorites:*\n\n" + "\n".join(f"• {label(c)}" for c in crops)
            if crops else
            "⭐ *Your Favorites:*\n\nNone yet."
        )
        await query.edit_message_text(text, parse_mode="Markdown",
                                     reply_markup=main_menu(data["fav_all"]))

    elif action == "favall":
        data["fav_all"] = True
        data["list"] = ALL_KEYS[:]
        await query.edit_message_text(
            "⭐🔥 Fav All enabled!",
            parse_mode="Markdown",
            reply_markup=main_menu(True),
        )

    elif action == "clearall":
        data["fav_all"] = False
        data["list"] = []
        await query.edit_message_text(
            "🔕 Cleared all alerts.",
            reply_markup=main_menu(False),
        )

    elif action == "add":
        available = [k for k in ALL_KEYS if k not in data["list"]]
        await query.edit_message_text(
            "➕ Pick crop:",
            reply_markup=crop_keyboard("add_", available),
        )

    elif action.startswith("add_"):
        key = action[4:]

        if key not in data["list"] and len(data["list"]) < MAX_CROPS:
            data["list"].append(key)

        await query.edit_message_text(
            f"Added {label(key)}",
            reply_markup=main_menu(data["fav_all"]),
        )

    elif action == "remove":
        await query.edit_message_text(
            "➖ Remove crop:",
            reply_markup=crop_keyboard("rem_", data["list"]),
        )

    elif action.startswith("rem_"):
        key = action[4:]
        if key in data["list"]:
            data["list"].remove(key)

        await query.edit_message_text(
            f"Removed {label(key)}",
            reply_markup=main_menu(data["fav_all"]),
        )


# ─────────────────────────────────────────
#  ALERT LOOP (UNCHANGED)
# ─────────────────────────────────────────
async def alert_loop(app):
    await asyncio.sleep(10)

    while True:
        try:
            contests = await fetch_contests()
            now_ms = time.time() * 1000

            for contest in contests:
                ts = contest["timestamp"]
                mins = minutes_until(ts)

                if not (8.0 < mins < 12.0):
                    continue

                for user_id, udata in list(user_data.items()):
                    matched = [
                        k for k in contest["crops"]
                        if udata["fav_all"] or k in udata["list"]
                    ]

                    if not matched:
                        continue

                    alert_id = (user_id, ts)
                    if alert_id in sent_alerts:
                        continue

                    msg = (
                        f"🚨 *{ '  '.join(label(k) for k in matched) } Contest*\n\n"
                        f"Starts in ~10 minutes!"
                    )

                    await app.bot.send_message(
                        chat_id=user_id,
                        text=msg,
                        parse_mode="Markdown",
                    )

                    sent_alerts.add(alert_id)

            stale = {a for a in sent_alerts if (now_ms - a[1]) > 2 * 3600 * 1000}
            sent_alerts.difference_update(stale)

        except Exception as e:
            print(f"[loop error] {e}")

        await asyncio.sleep(60)


# ─────────────────────────────────────────
#  STARTUP
# ─────────────────────────────────────────
async def post_init(app):
    asyncio.create_task(alert_loop(app))


def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("test", test_cmd))
    app.add_handler(CommandHandler("next", next_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("Bot running…")
    app.run_polling()


if __name__ == "__main__":
    main()
