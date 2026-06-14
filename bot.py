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
print(f"[startup] HYPIXEL_API_KEY = {HYPIXEL_API_KEY!r}")

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

# Elite leaderboard crop slugs
ELITE_CROP_SLUG = {
    "cactus":     "cactus",
    "carrot":     "carrot",
    "cocoa":      "cocoa",
    "melon":      "melon",
    "mushroom":   "mushroom",
    "netherwart": "netherwart",
    "potato":     "potato",
    "pumpkin":    "pumpkin",
    "sugarcane":  "sugarcane",
    "wheat":      "wheat",
    "sunflower":  "sunflower",
    "moonflower": "moonflower",
    "wildrose":   "wildrose",
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

MAX_CROPS   = 3
JACOB_API   = "https://jacobs.strassburger.dev/api/jacobcontests"
MOJANG_API  = "https://api.mojang.com/users/profiles/minecraft/{ign}"
HYPIXEL_API = "https://api.hypixel.net/v2/skyblock/profiles?uuid={uuid}"
ELITE_API   = "https://api.elitebot.dev/leaderboard/{crop}/{ign}"
ELITE_API_MONTHLY = "https://api.elitebot.dev/leaderboard/{crop}-monthly/{ign}"

# ─────────────────────────────────────────
#  STATE
# ─────────────────────────────────────────
user_data       = {}
sent_alerts     = set()
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
        [InlineKeyboardButton("⭐ My Favorites",  callback_data="fav")],
        [InlineKeyboardButton("➕ Add Crop",       callback_data="add")],
        [InlineKeyboardButton("➖ Remove Crop",    callback_data="remove")],
        [InlineKeyboardButton(
            "⭐🔥 Fav All  (ALL alerts ON)" if fav_all else "⭐ Fav All",
            callback_data="favall"
        )],
        [InlineKeyboardButton("🔕 Clear All",      callback_data="clearall")],
        [InlineKeyboardButton("📅 Next Contests",  callback_data="next")],
        [InlineKeyboardButton("🔍 Lookup Player",  callback_data="lookup")],
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
        [InlineKeyboardButton("🏆 All Time Best",    callback_data=f"lk_stat_{ign}_{crop}_alltime")],
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


async def get_elite_rank(ign: str, crop_key: str) -> tuple[int | None, int | None]:
    slug = ELITE_CROP_SLUG.get(crop_key, crop_key)
    alltime_rank = None
    monthly_rank = None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                ELITE_API.format(crop=slug, ign=ign),
                timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                print(f"[elite] alltime status: {resp.status} url: {ELITE_API.format(crop=slug, ign=ign)}")
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    print(f"[elite] alltime data: {data}")
                    alltime_rank = data.get("rank") or data.get("position")

            async with session.get(
                ELITE_API_MONTHLY.format(crop=slug, ign=ign),
                timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                print(f"[elite] monthly status: {resp.status} url: {ELITE_API_MONTHLY.format(crop=slug, ign=ign)}")
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    print(f"[elite] monthly data: {data}")
                    monthly_rank = data.get("rank") or data.get("position")

    except Exception as e:
        print(f"[Elite API error] {e}")
        import traceback
        traceback.print_exc()

    return alltime_rank, monthly_rank

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
        return

    waiting_for_ign.discard(user_id)
    ign = update.message.text.strip()

    msg  = await update.message.reply_text(f"🔍 Looking up *{ign}*…", parse_mode="Markdown")
    uuid = await get_uuid(ign)

    if not uuid:
        await msg.edit_text(
            f"❌ Player *{ign}* not found.\nCheck the spelling and try again.",
            parse_mode="Markdown",
            reply_markup=back_only(),
        )
        return

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
            star      = "⭐ " if any(k in data["list"] for k in c["crops"]) else ""
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
        crop_key = action.split("_")[-1]
        ign      = "_".join(action[8:].split("_")[:-1])
        await query.edit_message_text(
            f"📊 *{ign}* — {label(crop_key)}\n\nWhat do you want to see?",
            parse_mode="Markdown",
            reply_markup=lookup_period_keyboard(ign, crop_key),
        )

    # ── Lookup: period selected → fetch stats ──────────────────────────
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

        # Fetch Hypixel stats and Elite rank in parallel
        stats, (alltime_rank, monthly_rank) = await asyncio.gather(
            get_jacob_stats(uuid, crop_key, mode),
            get_elite_rank(ign, crop_key),
        )

        if stats is None:
            await query.edit_message_text(
                "⚠️ Hypixel API error. Try again in a moment.",
                reply_markup=back_only(),
            )
            return

        collection_total = stats.get("collection_total", 0)

        # Build rank line
        rank_parts = []
        if alltime_rank:
            rank_parts.append(f"#{alltime_rank} all time")
        if monthly_rank:
            rank_parts.append(f"#{monthly_rank} this month")
        rank_line = f"*Global Rank:* {' · '.join(rank_parts)}" if rank_parts else "*Global Rank:* unranked"

        if not stats.get("found"):
            await query.edit_message_text(
                f"😔 *{ign}* has no {label(crop_key)} contest data.\n\n"
                f"*Total Harvested:* {collection_total:,}\n"
                f"{rank_line}\n\n"
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
            rank_str = f"#{pos} out of {out_of}" if isinstance(pos, int) else "unknown rank"

            text = (
                f"🏆 *{ign}* — {label(crop_key)}\n\n"
                f"*Total Harvested:* {collection_total:,}\n"
                f"{rank_line}\n"
                f"*Best Score:* {stats['score']:,}\n"
                f"*Best Medal:* {emoji} {medal}\n"
                f"*Rank that run:* {rank_str}\n"
                f"*Total contests:* {stats['total']}"
            )

        else:
            lines = [
                f"📆 *{ign}* — {label(crop_key)} (last {len(stats['entries'])})\n",
                f"*Total Harvested:* {collection_total:,}",
                f"{rank_line}\n",
            ]
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
