import asyncio
import time
import aiohttp

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

TOKEN = "8957677405:AAG0kBcs7AW-3IvYgIxJm2IHplI15x3sJn0"

# ─────────────────────────────────────────
#  CROP DEFINITIONS
#  Keys match the integer codes the API returns (0–9)
# ─────────────────────────────────────────
CROP_MAP = {
    0: ("cactus",     "🌵 Cactus"),
    1: ("carrot",     "🥕 Carrot"),
    2: ("cocoa",      "🌰 Cocoa Beans"),
    3: ("melon",      "🍉 Melon"),
    4: ("mushroom",   "🍄 Mushroom"),
    5: ("netherwart", "🌌 Nether Wart"),
    6: ("potato",     "🥔 Potato"),
    7: ("pumpkin",    "🎃 Pumpkin"),
    8: ("sugarcane",  "🎋 Sugar Cane"),
    9: ("wheat",      "🌾 Wheat"),
}

# Reverse lookup: key string → (code, label)
KEY_TO_CODE  = {v[0]: k for k, v in CROP_MAP.items()}
KEY_TO_LABEL = {v[0]: v[1] for v in CROP_MAP.values()}

MAX_CROPS = 3
API_URL   = "https://jacobs.strassburger.dev/api/jacobcontests"

# ─────────────────────────────────────────
#  STATE
#  user_data[user_id] = {"fav_all": bool, "list": [key, ...]}
#  sent_alerts = {(user_id, crop_key, contest_timestamp_ms)}
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
        [InlineKeyboardButton("⭐ My Favorites",   callback_data="fav")],
        [InlineKeyboardButton("➕ Add Crop",        callback_data="add")],
        [InlineKeyboardButton("➖ Remove Crop",     callback_data="remove")],
        [InlineKeyboardButton(
            "⭐🔥 Fav All  (receiving ALL alerts)" if fav_all else "⭐ Fav All",
            callback_data="favall"
        )],
        [InlineKeyboardButton("🔕 Clear All",       callback_data="clearall")],
    ])


def crop_select_keyboard(prefix: str, keys: list[str]) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(label(k), callback_data=f"{prefix}{k}")] for k in keys]
    buttons.append([InlineKeyboardButton("« Back", callback_data="back")])
    return InlineKeyboardMarkup(buttons)


# ─────────────────────────────────────────
#  API
# ─────────────────────────────────────────
async def fetch_contests() -> list[dict]:
    """
    Returns a list of upcoming contests from the API.
    Each entry looks like:
        {"timestamp": 1781244900000, "crops": [9, 2, 5]}
    where crops is a list of integer crop codes.
    We only return contests that haven't started yet.
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(API_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json(content_type=None)

        now_ms = time.time() * 1000
        upcoming = []
        for contest in data:
            ts = contest.get("timestamp") or contest.get("time") or contest.get("start")
            crops_raw = contest.get("crops", [])

            if ts is None:
                continue

            # Normalise: the API sometimes returns crop objects, sometimes ints
            crop_codes = []
            for c in crops_raw:
                if isinstance(c, int):
                    crop_codes.append(c)
                elif isinstance(c, dict):
                    crop_codes.append(c.get("id", c.get("crop", -1)))

            crop_keys = [CROP_MAP[code][0] for code in crop_codes if code in CROP_MAP]

            if ts > now_ms:          # only future contests
                upcoming.append({"timestamp": ts, "crops": crop_keys})

        upcoming.sort(key=lambda x: x["timestamp"])
        return upcoming

    except Exception as e:
        print(f"[API error] {e}")
        return []


# ─────────────────────────────────────────
#  COMMANDS
# ─────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data    = get_user(user_id)
    await update.message.reply_text(
        "🌾 *Jacob's Farming Contest Bot*\n\n"
        "Get notified 10 minutes before your favourite crops are up for contest.\n\n"
        "Data provided by [jacobs.strassburger.dev](https://jacobs.strassburger.dev)",
        parse_mode="Markdown",
        reply_markup=main_menu(data["fav_all"]),
    )


async def test_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧪 Sending a test alert in 2 seconds…")
    await asyncio.sleep(2)
    await update.message.reply_text(
        "🚨 *TEST ALERT*\n\n🌾 Wheat Contest\nStarts in *10 minutes!*",
        parse_mode="Markdown",
    )


async def next_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the next few upcoming contests."""
    contests = await fetch_contests()
    if not contests:
        await update.message.reply_text("⚠️ Couldn't fetch contest data right now. Try again later.")
        return

    lines = ["📅 *Upcoming Contests:*\n"]
    for c in contests[:5]:
        mins = minutes_until(c["timestamp"])
        crop_labels = "  ".join(label(k) for k in c["crops"])
        if mins < 60:
            time_str = f"in {int(mins)}m"
        else:
            time_str = f"in {int(mins // 60)}h {int(mins % 60)}m"
        lines.append(f"{crop_labels}\n_starts {time_str}_\n")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ─────────────────────────────────────────
#  BUTTON HANDLER
# ─────────────────────────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data    = get_user(user_id)
    action  = query.data

    # ── Main menu ──────────────────────────────────────────────────────

    if action == "back":
        await query.edit_message_text(
            "🌾 *Jacob's Farming Contest Bot*\nChoose an option:",
            parse_mode="Markdown",
            reply_markup=main_menu(data["fav_all"]),
        )

    elif action == "fav":
        crops = data["list"]
        if crops:
            text = "⭐ *Your Favorites:*\n\n" + "\n".join(f"• {label(c)}" for c in crops)
        else:
            text = "⭐ *Your Favorites:*\n\nNone yet — use ➕ Add Crop to get started."
        await query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=main_menu(data["fav_all"]),
        )

    elif action == "favall":
        data["fav_all"] = True
        data["list"]    = list(KEY_TO_CODE.keys())   # all crops
        await query.edit_message_text(
            "⭐🔥 *Fav All* enabled!\n\nYou'll get alerts for every crop contest.",
            parse_mode="Markdown",
            reply_markup=main_menu(True),
        )

    elif action == "clearall":
        data["fav_all"] = False
        data["list"]    = []
        await query.edit_message_text(
            "🔕 Cleared. You won't receive any alerts until you add crops.",
            reply_markup=main_menu(False),
        )

    # ── Add ────────────────────────────────────────────────────────────

    elif action == "add":
        already  = set(data["list"])
        available = [k for k in KEY_TO_CODE if k not in already]
        if not available:
            await query.edit_message_text(
                "✅ You're already tracking all crops!",
                reply_markup=main_menu(data["fav_all"]),
            )
            return
        await query.edit_message_text(
            "➕ *Which crop do you want to add?*",
            parse_mode="Markdown",
            reply_markup=crop_select_keyboard("add_", available),
        )

    elif action.startswith("add_"):
        key = action[4:]
        if data["fav_all"]:
            await query.answer("Fav All is on — you already track everything.", show_alert=True)
            return
        if key in data["list"]:
            await query.answer("Already in your list.", show_alert=True)
            return
        if len(data["list"]) >= MAX_CROPS:
            await query.edit_message_text(
                f"⚠️ You can only track up to {MAX_CROPS} crops.\n"
                "Remove one first, or enable Fav All.",
                reply_markup=main_menu(data["fav_all"]),
            )
            return
        data["list"].append(key)
        await query.edit_message_text(
            f"✅ Added *{label(key)}* to your favorites!",
            parse_mode="Markdown",
            reply_markup=main_menu(data["fav_all"]),
        )

    # ── Remove ─────────────────────────────────────────────────────────

    elif action == "remove":
        if not data["list"]:
            await query.edit_message_text(
                "Nothing to remove.", reply_markup=main_menu(data["fav_all"])
            )
            return
        await query.edit_message_text(
            "➖ *Which crop do you want to remove?*",
            parse_mode="Markdown",
            reply_markup=crop_select_keyboard("rem_", data["list"]),
        )

    elif action.startswith("rem_"):
        key = action[4:]
        if key in data["list"]:
            data["list"].remove(key)
            if data["fav_all"]:
                data["fav_all"] = False   # partial removal exits fav_all mode
        await query.edit_message_text(
            f"🗑 Removed *{label(key)}*.",
            parse_mode="Markdown",
            reply_markup=main_menu(data["fav_all"]),
        )


# ─────────────────────────────────────────
#  ALERT LOOP
# ─────────────────────────────────────────
async def alert_loop(app):
    await asyncio.sleep(10)   # give bot time to start

    while True:
        try:
            contests = await fetch_contests()
            print(f"[loop] fetched {len(contests)} upcoming contests")

            for contest in contests:
                ts         = contest["timestamp"]
                crop_keys  = contest["crops"]
                mins       = minutes_until(ts)

                # Trigger window: between 9.5 and 11 minutes out
                if not (9.5 < mins < 11.0):
                    continue

                for user_id, udata in list(user_data.items()):
                    for key in crop_keys:
                        if not (udata["fav_all"] or key in udata["list"]):
                            continue

                        alert_id = (user_id, key, ts)
                        if alert_id in sent_alerts:
                            continue

                        try:
                            await app.bot.send_message(
                                chat_id=user_id,
                                text=(
                                    f"🚨 *{label(key)} Contest*\n\n"
                                    f"Starts in *~10 minutes!*\n\n"
                                    f"_Also in this contest:_ "
                                    + "  ".join(label(k) for k in crop_keys if k != key)
                                ),
                                parse_mode="Markdown",
                            )
                            sent_alerts.add(alert_id)
                        except Exception as e:
                            print(f"[send error] user {user_id}: {e}")

            # Prune old alert IDs so the set doesn't grow forever
            now_ms = time.time() * 1000
            stale  = {a for a in sent_alerts if (now_ms - a[2]) > 2 * 3600 * 1000}
            sent_alerts.difference_update(stale)

        except Exception as e:
            print(f"[loop error] {e}")

        await asyncio.sleep(60)   # poll every 60 seconds — contests are hourly


# ─────────────────────────────────────────
#  STARTUP
# ─────────────────────────────────────────
async def post_init(app):
    asyncio.create_task(alert_loop(app))


# ─────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────
def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("test",   test_cmd))
    app.add_handler(CommandHandler("next",   next_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("Bot running…")
    app.run_polling()


if __name__ == "__main__":
    main()