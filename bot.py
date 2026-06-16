import asyncio
import time
import aiohttp
import os

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

TOKEN           = os.environ.get("BOT_TOKEN")
HYPIXEL_API_KEY = os.environ.get("HYPIXEL_API_KEY")

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

HYPIXEL_CROP_KEY = {
    "cactus":     "CACTUS",
    "carrot":     "CARROT",
    "cocoa":      "COCOA_BEANS",
    "melon":      "MELON",
    "mushroom":   "MUSHROOM",
    "netherwart": "NETHER_WART",
    "potato":     "POTATO",
    "pumpkin":    "PUMPKIN",
    "sugarcane":  "SUGAR_CANE",
    "wheat":      "WHEAT",
    "sunflower":  "SUNFLOWER",
    "moonflower": "MOONFLOWER",
    "wildrose":   "WILD_ROSE",
}

COLLECTION_CROP_KEY = {
    "cactus":     "CACTUS",
    "carrot":     "CARROT_ITEM",
    "cocoa":      "INK_SACK:3",
    "melon":      "MELON",
    "mushroom":   "MUSHROOM_COLLECTION",
    "netherwart": "NETHER_STALK",
    "potato":     "POTATO_ITEM",
    "pumpkin":    "PUMPKIN",
    "sugarcane":  "SUGAR_CANE",
    "wheat":      "WHEAT",
    "sunflower":  "SUNFLOWER",
    "moonflower": "MOONFLOWER",
    "wildrose":   "WILDROSE",
}

MEDAL_EMOJI = {
    "BRONZE":   "🥉",
    "SILVER":   "🥈",
    "GOLD":     "🥇",
    "PLATINUM": "💎",
    "DIAMOND":  "💠",
}

KEY_TO_CODE  = {v[0]: k    for k, v in CROP_MAP.items()}
KEY_TO_LABEL = {v[0]: v[1] for v in CROP_MAP.values()}
ALL_KEYS     = list(KEY_TO_CODE.keys())

MAX_CROPS      = 3

JACOB_API   = "https://jacobs.strassburger.dev/api/jacobcontests"
MOJANG_API  = "https://api.mojang.com/users/profiles/minecraft/{ign}"
HYPIXEL_API = "https://api.hypixel.net/v2/skyblock/profiles?uuid={uuid}"

# ─────────────────────────────────────────
#  REPLY KEYBOARD BUTTON LABELS
#  These are the text strings the bottom toolbar sends as messages
# ─────────────────────────────────────────
BTN_FAVORITES  = "⭐ Favorites"
BTN_ADD        = "➕ Add Crop"
BTN_REMOVE     = "➖ Remove"
BTN_NEXT       = "📅 Next Contests"
BTN_LOOKUP     = "🔍 Lookup Player"
BTN_FAVALL     = "⭐ Fav All"
BTN_CLEARALL   = "🔕 Clear All"

TOOLBAR_BUTTONS = {BTN_FAVORITES, BTN_ADD, BTN_REMOVE, BTN_NEXT, BTN_LOOKUP, BTN_FAVALL, BTN_CLEARALL}

# ─────────────────────────────────────────
#  STATE
# ─────────────────────────────────────────
user_data       = {}
sent_alerts     = set()
waiting_for_ign = set()
lookup_log      = {}

WINDOW = 24 * 3600


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
#  RATE LIMIT
# ─────────────────────────────────────────
def check_lookup_limit(user_id: int, ign: str) -> tuple[bool, str]:
    if ign.lower() in WHITELIST_IGNS:
        return True, ""

    now     = time.time()
    history = [t for t in lookup_log.get(user_id, []) if now - t < WINDOW]
    lookup_log[user_id] = history

    if len(history) >= DAILY_LOOKUPS:
        oldest    = min(history)
        resets_in = WINDOW - (now - oldest)
        hours     = int(resets_in // 3600)
        mins      = int((resets_in % 3600) // 60)
        reset_str = f"{hours}h {mins}m" if hours else f"{mins}m"
        return False, (
            f"⏳ You've used all {DAILY_LOOKUPS} lookups for today.\n\n"
            f"Resets in *{reset_str}*."
        )
    return True, ""

def record_lookup(user_id: int):
    lookup_log.setdefault(user_id, []).append(time.time())


# ─────────────────────────────────────────
#  KEYBOARDS
# ─────────────────────────────────────────
def toolbar() -> ReplyKeyboardMarkup:
    """Persistent bottom toolbar — always visible."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(BTN_FAVORITES), KeyboardButton(BTN_ADD),    KeyboardButton(BTN_REMOVE)],
            [KeyboardButton(BTN_NEXT),      KeyboardButton(BTN_LOOKUP), KeyboardButton(BTN_FAVALL)],
            [KeyboardButton(BTN_CLEARALL)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )

def back_button() -> list:
    return [InlineKeyboardButton("« Back", callback_data="back")]

def back_only() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([back_button()])

def inline_crop_keyboard(prefix: str, keys: list) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(label(k), callback_data=f"{prefix}{k}")] for k in keys]
    buttons.append(back_button())
    return InlineKeyboardMarkup(buttons)

def lookup_crop_keyboard(ign: str) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(label(k), callback_data=f"lk_crop_{ign}_{k}")] for k in ALL_KEYS]
    buttons.append(back_button())
    return InlineKeyboardMarkup(buttons)

def lookup_period_keyboard(ign: str, crop: str) -> InlineKeyboardMarkup:
    crop_label = label(crop).split(" ", 1)[-1]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"🏆 Best {crop_label} Contest (All Time)",
            callback_data=f"lk_stat_{ign}_{crop}_alltime"
        )],
        [InlineKeyboardButton(
            f"📆 Last 10 {crop_label} Contests",
            callback_data=f"lk_stat_{ign}_{crop}_recent"
        )],
        back_button(),
    ])


# ─────────────────────────────────────────
#  JACOB CONTEST API
# ─────────────────────────────────────────
async def fetch_contests() -> list:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(JACOB_API, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json(content_type=None)

        now_ms   = time.time() * 1000
        upcoming = []

        for contest in data:
            ts = contest.get("timestamp") or contest.get("time") or contest.get("start")
            if not ts or ts <= now_ms:
                continue

            crops_raw  = contest.get("crops", [])
            crop_codes = []
            for c in crops_raw:
                if isinstance(c, int):
                    crop_codes.append(c)
                elif isinstance(c, dict):
                    crop_codes.append(c.get("id", c.get("crop", -1)))

            crop_keys = []
            for code in crop_codes:
                if code in CROP_MAP:
                    crop_keys.append(CROP_MAP[code][0])
                else:
                    print(f"[unknown crop code] {code}")

            upcoming.append({"timestamp": ts, "crops": crop_keys})

        upcoming.sort(key=lambda x: x["timestamp"])
        return upcoming

    except Exception as e:
        print(f"[API error] {e}")
        return []


# ─────────────────────────────────────────
#  HYPIXEL PLAYER LOOKUP
# ─────────────────────────────────────────
async def get_uuid(ign: str) -> str | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                MOJANG_API.format(ign=ign),
                timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data.get("id")
    except Exception:
        return None


async def get_jacob_stats(uuid: str, crop_key: str, mode: str) -> dict | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                HYPIXEL_API.format(uuid=uuid),
                headers={"API-Key": HYPIXEL_API_KEY},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

        if not data.get("success"):
            return None

        profiles = data.get("profiles", [])
        if not profiles:
            return None

        profile = max(profiles, key=lambda p: p.get("last_save", 0))
        members = profile.get("members", {})
        member  = members.get(uuid, {})

        if not member:
            return None

        collection       = member.get("collection", {})
        ckey             = COLLECTION_CROP_KEY.get(crop_key, "")
        collection_total = collection.get(ckey, 0)

        jacob = member.get("jacobs_contest") or member.get("jacob2") or member.get("jacob", {})
        if not jacob:
            return None

        contests = jacob.get("contests", {})
        hkey     = HYPIXEL_CROP_KEY.get(crop_key, "")

        crop_contests = {
            k: v for k, v in contests.items()
            if f":{hkey}" in k
        }

        if not crop_contests:
            return {"found": False, "collection_total": collection_total}

        sorted_contests = sorted(crop_contests.items(), key=lambda x: x[0], reverse=True)

        if mode == "alltime":
            best = max(crop_contests.values(), key=lambda c: c.get("collected", 0))
            return {
                "found":            True,
                "mode":             "alltime",
                "score":            best.get("collected", 0),
                "medal":            best.get("claimed_medal", "NONE").upper(),
                "position":         best.get("claimed_position", "?"),
                "out_of":           best.get("claimed_participants", "?"),
                "total":            len(crop_contests),
                "collection_total": collection_total,
            }
        else:
            recent  = sorted_contests[:10]
            entries = []
            for _, v in recent:
                entries.append({
                    "score": v.get("collected", 0),
                    "medal": v.get("claimed_medal", "NONE").upper(),
                })
            return {
                "found":            True,
                "mode":             "recent",
                "entries":          entries,
                "total":            len(crop_contests),
                "collection_total": collection_total,
            }

    except Exception as e:
        print(f"[Hypixel API error] {e}")
        import traceback
        traceback.print_exc()
        return None


# ─────────────────────────────────────────
#  COMMANDS
# ─────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌾 *Jacob's Farming Contest Bot*\n\n"
        "Get notified 10 minutes before your favourite crops contest.\n\n"
        "Use the buttons below to get started.\n\n"
        "_Data by_ [jacobs.strassburger.dev](https://jacobs.strassburger.dev)",
        parse_mode="Markdown",
        reply_markup=toolbar(),
    )


async def test_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧪 Sending a test alert in 2 seconds…")
    await asyncio.sleep(2)
    await update.message.reply_text(
        "🚨 *🌾 Wheat  🥕 Carrot Contest*\n\n"
        "Starts in *~10 minutes!*\n\n"
        "_Also in this contest:_ 🍄 Mushroom",
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────
#  TOOLBAR TEXT HANDLER
#  Handles both toolbar button presses AND IGN text entry
# ─────────────────────────────────────────
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text    = update.message.text.strip()
    data    = get_user(user_id)

    # ── IGN entry (user is mid-lookup flow) ───────────────────────────
    if user_id in waiting_for_ign and text not in TOOLBAR_BUTTONS:
        waiting_for_ign.discard(user_id)
        ign = text

        allowed, limit_msg = check_lookup_limit(user_id, ign)
        if not allowed:
            await update.message.reply_text(limit_msg, parse_mode="Markdown")
            return

        msg  = await update.message.reply_text(f"🔍 Looking up *{ign}*…", parse_mode="Markdown")
        uuid = await get_uuid(ign)

        if not uuid:
            await msg.edit_text(
                f"❌ Player *{ign}* not found.\nCheck the spelling and try again.",
                parse_mode="Markdown",
            )
            return

        record_lookup(user_id)
        context.user_data["lookup_ign"]  = ign
        context.user_data["lookup_uuid"] = uuid

        await msg.edit_text(
            f"✅ Found *{ign}*!\n\nWhich crop do you want to check?",
            parse_mode="Markdown",
            reply_markup=lookup_crop_keyboard(ign),
        )
        return

    # ── Toolbar buttons ────────────────────────────────────────────────

    if text == BTN_FAVORITES:
        crops = data["list"]
        reply = (
            "⭐ *Your Favorites:*\n\n" + "\n".join(f"• {label(c)}" for c in crops)
            if crops else
            "⭐ *Your Favorites:*\n\nNone yet — tap ➕ Add Crop to get started."
        )
        await update.message.reply_text(reply, parse_mode="Markdown")

    elif text == BTN_ADD:
        waiting_for_ign.discard(user_id)
        available = [k for k in ALL_KEYS if k not in data["list"]]
        if not available:
            await update.message.reply_text("✅ *You're already tracking all crops!*", parse_mode="Markdown")
            return
        await update.message.reply_text(
            "➕ *Which crop do you want to add?*",
            parse_mode="Markdown",
            reply_markup=inline_crop_keyboard("add_", available),
        )

    elif text == BTN_REMOVE:
        waiting_for_ign.discard(user_id)
        if not data["list"]:
            await update.message.reply_text("ℹ️ *Nothing to remove.*", parse_mode="Markdown")
            return
        await update.message.reply_text(
            "➖ *Which crop do you want to remove?*",
            parse_mode="Markdown",
            reply_markup=inline_crop_keyboard("rem_", data["list"]),
        )

    elif text == BTN_NEXT:
        waiting_for_ign.discard(user_id)
        contests = await fetch_contests()
        if not contests:
            await update.message.reply_text("⚠️ Couldn't fetch data right now. Try again later.")
            return

        lines = ["📅 *Upcoming Contests:*\n"]
        for c in contests[:6]:
            mins      = minutes_until(c["timestamp"])
            crop_text = "  ".join(label(k) for k in c["crops"])
            time_str  = f"in {int(mins)}m" if mins < 60 else f"in {int(mins // 60)}h {int(mins % 60)}m"
            star      = "⭐ " if any(k in data["list"] for k in c["crops"]) else ""
            lines.append(f"{star}{crop_text}\n_starts {time_str}_\n")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    elif text == BTN_LOOKUP:
        waiting_for_ign.add(user_id)
        await update.message.reply_text(
            "🔍 *Player Lookup*\n\nType your Minecraft IGN:",
            parse_mode="Markdown",
        )

    elif text == BTN_FAVALL:
        waiting_for_ign.discard(user_id)
        data["fav_all"] = True
        data["list"]    = ALL_KEYS[:]
        await update.message.reply_text(
            "⭐🔥 *Fav All enabled!*\n\nYou'll get alerts for every crop contest.",
            parse_mode="Markdown",
        )

    elif text == BTN_CLEARALL:
        waiting_for_ign.discard(user_id)
        data["fav_all"] = False
        data["list"]    = []
        await update.message.reply_text(
            "🔕 *Cleared.*\n\nNo alerts until you add crops again.",
            parse_mode="Markdown",
        )


# ─────────────────────────────────────────
#  INLINE BUTTON HANDLER (submenus only)
# ─────────────────────────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data    = get_user(user_id)
    action  = query.data

    # ── Back — just close the inline menu cleanly ──────────────────────
    if action == "back":
        waiting_for_ign.discard(user_id)
        await query.delete_message()

    # ── Add crop ───────────────────────────────────────────────────────
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
                f"⚠️ *Max {MAX_CROPS} crops reached.*\n\nRemove one first, or tap ⭐ Fav All.",
                parse_mode="Markdown",
                reply_markup=back_only(),
            )
            return
        data["list"].append(key)
        await query.edit_message_text(
            f"✅ *{label(key)}* added to your favorites!",
            parse_mode="Markdown",
            reply_markup=back_only(),
        )

    # ── Remove crop ────────────────────────────────────────────────────
    elif action.startswith("rem_"):
        key = action[4:]
        if key in data["list"]:
            data["list"].remove(key)
        if data["fav_all"]:
            data["fav_all"] = False
        await query.edit_message_text(
            f"🗑 *{label(key)}* removed.",
            parse_mode="Markdown",
            reply_markup=back_only(),
        )

    # ── Lookup: crop selected ──────────────────────────────────────────
    elif action.startswith("lk_crop_"):
        crop_key = action.split("_")[-1]
        ign      = "_".join(action[8:].split("_")[:-1])
        await query.edit_message_text(
            f"📊 *{ign}* — {label(crop_key)}\n\nWhat do you want to see?",
            parse_mode="Markdown",
            reply_markup=lookup_period_keyboard(ign, crop_key),
        )

    # ── Lookup: period → fetch stats ───────────────────────────────────
    elif action.startswith("lk_stat_"):
        parts    = action[8:].split("_")
        mode     = parts[-1]
        crop_key = parts[-2]
        ign      = "_".join(parts[:-2])

        await query.edit_message_text(
            f"⏳ Fetching stats for *{ign}*…",
            parse_mode="Markdown",
        )

        uuid = context.user_data.get("lookup_uuid")
        if not uuid:
            uuid = await get_uuid(ign)

        if not uuid:
            await query.edit_message_text(
                "❌ Couldn't find that player. Try looking them up again.",
                reply_markup=back_only(),
            )
            return

        stats = await get_jacob_stats(uuid, crop_key, mode)

        if stats is None:
            await query.edit_message_text(
                "⚠️ Hypixel API error. Try again in a moment.",
                reply_markup=back_only(),
            )
            return

        collection_total = stats.get("collection_total", 0)
        crop_label       = label(crop_key)

        if not stats.get("found"):
            await query.edit_message_text(
                f"😔 *{ign}* has no {crop_label} contest data.\n\n"
                f"*Total Harvested:* {collection_total:,}\n\n"
                "They may not have participated in any contests, or their profile is private.",
                parse_mode="Markdown",
                reply_markup=back_only(),
            )
            return

        if mode == "alltime":
            medal    = stats["medal"]
            emoji    = MEDAL_EMOJI.get(medal, "❓")
            pos      = stats["position"]
            out_of   = stats["out_of"]
            rank_str = f"#{pos} out of {out_of}" if isinstance(pos, int) else "unknown"

            text = (
                f"🏆 *{ign}* — Best {crop_label} Contest of All Time\n\n"
                f"*Total Harvested:* {collection_total:,}\n"
                f"*Best Score:* {stats['score']:,}\n"
                f"*Best Medal:* {emoji} {medal}\n"
                f"*Rank that run:* {rank_str}\n"
                f"*Total {crop_label} contests:* {stats['total']}"
            )
        else:
            lines = [
                f"📆 *{ign}* — Last {len(stats['entries'])} {crop_label} Contests\n",
                f"*Total Harvested:* {collection_total:,}\n",
            ]
            for i, e in enumerate(stats["entries"], 1):
                medal = e["medal"]
                emoji = MEDAL_EMOJI.get(medal, "❓")
                lines.append(f"{i}. {e['score']:,}  {emoji} {medal}")
            lines.append(f"\n_Total {crop_label} contests: {stats['total']}_")
            text = "\n".join(lines)

        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=back_only())


# ─────────────────────────────────────────
#  ALERT LOOP
# ─────────────────────────────────────────
async def alert_loop(app):
    await asyncio.sleep(10)

    while True:
        try:
            contests = await fetch_contests()
            print(f"[loop] fetched {len(contests)} upcoming contests")

            now_ms = time.time() * 1000

            for contest in contests:
                ts        = contest["timestamp"]
                crop_keys = contest["crops"]
                mins      = minutes_until(ts)

                if not (8.0 < mins < 12.0):
                    continue

                for user_id, udata in list(user_data.items()):
                    matched = [k for k in crop_keys if udata["fav_all"] or k in udata["list"]]

                    if not matched:
                        continue

                    alert_id = (user_id, ts)
                    if alert_id in sent_alerts:
                        continue

                    others       = [k for k in crop_keys if k not in matched]
                    matched_text = "  ".join(label(k) for k in matched)
                    others_text  = "  ".join(label(k) for k in others)

                    msg = f"🚨 *{matched_text} Contest*\n\nStarts in *~10 minutes!*"
                    if others_text:
                        msg += f"\n\n_Also in this contest:_ {others_text}"

                    try:
                        await app.bot.send_message(chat_id=user_id, text=msg, parse_mode="Markdown")
                        sent_alerts.add(alert_id)
                    except Exception as e:
                        print(f"[send error] user {user_id}: {e}")

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


# ─────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────
def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("test",  test_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("Bot running…")
    app.run_polling()


if __name__ == "__main__":
    main()
