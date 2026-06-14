import asyncio
import time
import aiohttp
import os

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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

# Hypixel API uses these internal crop name strings
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

MEDAL_EMOJI = {
    "BRONZE":   "🥉",
    "SILVER":   "🥈",
    "GOLD":     "🥇",
    "PLATINUM": "💎",
    "DIAMOND":  "💠",
}

KEY_TO_CODE  = {v[0]: k   for k, v in CROP_MAP.items()}
KEY_TO_LABEL = {v[0]: v[1] for v in CROP_MAP.values()}
ALL_KEYS     = list(KEY_TO_CODE.keys())

MAX_CROPS = 3
JACOB_API = "https://jacobs.strassburger.dev/api/jacobcontests"
MOJANG_API = "https://api.mojang.com/users/profiles/minecraft/{ign}"
HYPIXEL_API = "https://api.hypixel.net/v2/skyblock/profiles?uuid={uuid}"

# ─────────────────────────────────────────
#  STATE
# ─────────────────────────────────────────
user_data    = {}   # {user_id: {"fav_all": bool, "list": [key, ...]}}
sent_alerts  = set()
# Tracks users currently in "waiting for IGN" state
waiting_for_ign = set()


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
def back_button() -> list:
    return [InlineKeyboardButton("« Back", callback_data="back")]

def main_menu(fav_all: bool = False) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ My Favorites",   callback_data="fav")],
        [InlineKeyboardButton("➕ Add Crop",        callback_data="add")],
        [InlineKeyboardButton("➖ Remove Crop",     callback_data="remove")],
        [InlineKeyboardButton(
            "⭐🔥 Fav All  (ALL alerts ON)" if fav_all else "⭐ Fav All",
            callback_data="favall"
        )],
        [InlineKeyboardButton("🔕 Clear All",       callback_data="clearall")],
        [InlineKeyboardButton("📅 Next Contests",   callback_data="next")],
        [InlineKeyboardButton("🔍 Lookup Player",   callback_data="lookup")],
    ])

def back_only() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([back_button()])

def crop_keyboard(prefix: str, keys: list) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(label(k), callback_data=f"{prefix}{k}")] for k in keys]
    buttons.append(back_button())
    return InlineKeyboardMarkup(buttons)

def lookup_crop_keyboard(ign: str) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(label(k), callback_data=f"lk_crop_{ign}_{k}")] for k in ALL_KEYS]
    buttons.append(back_button())
    return InlineKeyboardMarkup(buttons)

def lookup_period_keyboard(ign: str, crop: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏆 All Time Best",  callback_data=f"lk_stat_{ign}_{crop}_alltime")],
        [InlineKeyboardButton("📆 Recent (last 10)", callback_data=f"lk_stat_{ign}_{crop}_recent")],
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
    """Convert IGN → UUID via Mojang API."""
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
    """
    Fetch a player's Jacob contest stats from Hypixel API.
    Returns a dict with best score, medal, and recent results.
    mode: "alltime" | "recent"
    """
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

        # Use the last active profile
        profile = max(profiles, key=lambda p: p.get("last_save", 0) if isinstance(p.get("members"), dict) else 0)

        members = profile.get("members", {})
        member  = members.get(uuid.replace("-", ""), {})
        jacob   = member.get("jacob2") or member.get("jacob", {})

        if not jacob:
            return None

        contests = jacob.get("contests", {})
        hkey     = HYPIXEL_CROP_KEY.get(crop_key, "")

        # Filter contests for this crop
        crop_contests = {
            k: v for k, v in contests.items()
            if f":{hkey}" in k
        }

        if not crop_contests:
            return {"found": False}

        # Sort by timestamp (key format: "year:month:day:CROP")
        sorted_contests = sorted(crop_contests.items(), key=lambda x: x[0], reverse=True)

        if mode == "alltime":
            best = max(crop_contests.values(), key=lambda c: c.get("collected", 0))
            return {
                "found":     True,
                "mode":      "alltime",
                "score":     best.get("collected", 0),
                "medal":     best.get("claimed_medal", "NONE").upper(),
                "position":  best.get("claimed_position", "?"),
                "out_of":    best.get("claimed_participants", "?"),
                "total":     len(crop_contests),
            }

        else:  # recent
            recent = sorted_contests[:10]
            entries = []
            for _, v in recent:
                entries.append({
                    "score":  v.get("collected", 0),
                    "medal":  v.get("claimed_medal", "NONE").upper(),
                })
            return {
                "found":   True,
                "mode":    "recent",
                "entries": entries,
                "total":   len(crop_contests),
            }

    except Exception as e:
        print(f"[Hypixel API error] {e}")
        return None


# ─────────────────────────────────────────
#  COMMANDS
# ─────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = get_user(update.effective_user.id)
    await update.message.reply_text(
        "🌾 *Jacob's Farming Contest Bot*\n\n"
        "Get notified 10 minutes before your favourite crops contest.\n\n"
        "_Data by_ [jacobs.strassburger.dev](https://jacobs.strassburger.dev)",
        parse_mode="Markdown",
        reply_markup=main_menu(data["fav_all"]),
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
#  FREE TEXT HANDLER (IGN entry)
# ─────────────────────────────────────────
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in waiting_for_ign:
        return  # ignore unrelated messages

    waiting_for_ign.discard(user_id)
    ign = update.message.text.strip()

    msg = await update.message.reply_text(f"🔍 Looking up *{ign}*…", parse_mode="Markdown")

    uuid = await get_uuid(ign)
    if not uuid:
        await msg.edit_text(
            f"❌ Player *{ign}* not found.\nCheck the spelling and try again.",
            parse_mode="Markdown",
            reply_markup=back_only(),
        )
        return

    # Store IGN in context for next steps
    context.user_data["lookup_ign"]  = ign
    context.user_data["lookup_uuid"] = uuid

    await msg.edit_text(
        f"✅ Found *{ign}*!\n\nWhich crop do you want to check?",
        parse_mode="Markdown",
        reply_markup=lookup_crop_keyboard(ign),
    )


# ─────────────────────────────────────────
#  BUTTON HANDLER
# ─────────────────────────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data    = get_user(user_id)
    action  = query.data

    # ── Back ───────────────────────────────────────────────────────────
    if action == "back":
        waiting_for_ign.discard(user_id)
        await query.edit_message_text(
            "🌾 *Jacob's Farming Contest Bot*\nChoose an option:",
            parse_mode="Markdown",
            reply_markup=main_menu(data["fav_all"]),
        )

    # ── My Favorites ───────────────────────────────────────────────────
    elif action == "fav":
        crops = data["list"]
        text  = (
            "⭐ *Your Favorites:*\n\n" + "\n".join(f"• {label(c)}" for c in crops)
            if crops else
            "⭐ *Your Favorites:*\n\nNone yet — use ➕ Add Crop to get started."
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=back_only())

    # ── Fav All ────────────────────────────────────────────────────────
    elif action == "favall":
        data["fav_all"] = True
        data["list"]    = ALL_KEYS[:]
        await query.edit_message_text(
            "⭐🔥 *Fav All enabled!*\n\nYou'll get alerts for every crop contest.",
            parse_mode="Markdown",
            reply_markup=back_only(),
        )

    # ── Clear All ──────────────────────────────────────────────────────
    elif action == "clearall":
        data["fav_all"] = False
        data["list"]    = []
        await query.edit_message_text(
            "🔕 *Cleared.*\n\nNo alerts until you add crops again.",
            parse_mode="Markdown",
            reply_markup=back_only(),
        )

    # ── Next Contests ──────────────────────────────────────────────────
    elif action == "next":
        contests = await fetch_contests()
        if not contests:
            await query.edit_message_text(
                "⚠️ Couldn't fetch data right now. Try again later.",
                reply_markup=back_only(),
            )
            return

        lines = ["📅 *Upcoming Contests:*\n"]
        for c in contests[:6]:
            mins      = minutes_until(c["timestamp"])
            crop_text = "  ".join(label(k) for k in c["crops"])
            time_str  = f"in {int(mins)}m" if mins < 60 else f"in {int(mins // 60)}h {int(mins % 60)}m"
            # Star if any of user's favourites are in this contest
            star = "⭐ " if any(k in data["list"] for k in c["crops"]) else ""
            lines.append(f"{star}{crop_text}\n_starts {time_str}_\n")

        await query.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=back_only())

    # ── Add menu ───────────────────────────────────────────────────────
    elif action == "add":
        available = [k for k in ALL_KEYS if k not in data["list"]]
        if not available:
            await query.edit_message_text(
                "✅ *You're already tracking all crops!*",
                parse_mode="Markdown",
                reply_markup=back_only(),
            )
            return
        await query.edit_message_text(
            "➕ *Which crop do you want to add?*",
            parse_mode="Markdown",
            reply_markup=crop_keyboard("add_", available),
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
                f"⚠️ *Max {MAX_CROPS} crops reached.*\n\nRemove one first, or use Fav All.",
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

    # ── Remove menu ────────────────────────────────────────────────────
    elif action == "remove":
        if not data["list"]:
            await query.edit_message_text(
                "ℹ️ *Nothing to remove.*",
                parse_mode="Markdown",
                reply_markup=back_only(),
            )
            return
        await query.edit_message_text(
            "➖ *Which crop do you want to remove?*",
            parse_mode="Markdown",
            reply_markup=crop_keyboard("rem_", data["list"]),
        )

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

    # ── Lookup Player ──────────────────────────────────────────────────
    elif action == "lookup":
        waiting_for_ign.add(user_id)
        await query.edit_message_text(
            "🔍 *Player Lookup*\n\nType your Minecraft IGN:",
            parse_mode="Markdown",
            reply_markup=back_only(),
        )

    # ── Lookup: crop selected ──────────────────────────────────────────
    elif action.startswith("lk_crop_"):
        # format: lk_crop_{ign}_{cropkey}
        parts    = action[8:].split("_", 1)  # split on first _ only for ign, then crop
        # ign may contain underscores so we stored it differently — re-split from end
        crop_key = action.split("_")[-1]
        ign      = "_".join(action[8:].split("_")[:-1])

        await query.edit_message_text(
            f"📊 *{ign}* — {label(crop_key)}\n\nWhat do you want to see?",
            parse_mode="Markdown",
            reply_markup=lookup_period_keyboard(ign, crop_key),
        )

    # ── Lookup: period selected → fetch stats ──────────────────────────
    elif action.startswith("lk_stat_"):
        # format: lk_stat_{ign}_{cropkey}_{mode}
        parts    = action[8:].split("_")
        mode     = parts[-1]          # alltime | recent
        crop_key = parts[-2]          # e.g. wheat
        ign      = "_".join(parts[:-2])

        await query.edit_message_text(
            f"⏳ Fetching stats for *{ign}*…",
            parse_mode="Markdown",
        )

        uuid = context.user_data.get("lookup_uuid")
        if not uuid:
            # Re-fetch UUID if lost (e.g. after bot restart)
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

        if not stats.get("found"):
            await query.edit_message_text(
                f"😔 *{ign}* has no {label(crop_key)} contest data.\n\n"
                "They may not have participated in any, or their profile is private.",
                parse_mode="Markdown",
                reply_markup=back_only(),
            )
            return

        if mode == "alltime":
            medal   = stats["medal"]
            emoji   = MEDAL_EMOJI.get(medal, "❓")
            pos     = stats["position"]
            out_of  = stats["out_of"]
            rank_str = f"#{pos} out of {out_of}" if isinstance(pos, int) else "unknown rank"

            text = (
                f"🏆 *{ign}* — {label(crop_key)}\n\n"
                f"*Best Score:* {stats['score']:,}\n"
                f"*Best Medal:* {emoji} {medal}\n"
                f"*Rank that run:* {rank_str}\n"
                f"*Total contests:* {stats['total']}"
            )

        else:  # recent
            lines = [f"📆 *{ign}* — {label(crop_key)} (last {len(stats['entries'])})\n"]
            for i, e in enumerate(stats["entries"], 1):
                medal = e["medal"]
                emoji = MEDAL_EMOJI.get(medal, "❓")
                lines.append(f"{i}. {e['score']:,}  {emoji} {medal}")
            lines.append(f"\n_Total contests: {stats['total']}_")
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

            # Prune old alert IDs (older than 2 hours)
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
