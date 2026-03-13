#!/usr/bin/env python3
"""
🎮 Dota 2 Telegram Bot — @ErniFidBot
"""

import logging
import asyncio
import aiohttp
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN           = "8356191098:AAFu3axbr5OaEDlYyRUK_bhNKj1Zty8Za8Y"
STEAM_API_KEY   = "F25FE222BDDD5D2687073BAEF0D8CBB8"
ALLOWED_CHAT_ID = -1003719823975

PLAYERS = {
    "limon1705":      "76561199015459521",
    "wa6ingtonn":     "76561198312814207",
    "areembee":       "76561198385353313",
    "Tawer4K":        "76561198841600203",
    "neskvikcpivom2": "76561199004933239",
    "beekssus":       "76561198881056614"
}

DEFAULT_TAGS = list(PLAYERS.keys())
HOST_TG      = "wa6ingtonn"
HOST_ID      = PLAYERS[HOST_TG]

# Telegram username (lowercase) -> steam_id
TG_TO_STEAM = {tg.lower(): sid for tg, sid in PLAYERS.items()}

sessions:         dict[int, dict] = {}
reported_matches: set[str]        = set()
last_known_match: str | None      = None
HERO_NAMES:       dict[int, str]  = {}
ITEM_NAMES:       dict[int, str]  = {}

# ─── helpers ─────────────────────────────────────────────────────────────────

async def group_only(update: Update) -> bool:
    return update.effective_chat.id == ALLOWED_CHAT_ID

def all_mentions() -> str:
    return " ".join(f"@{u}" for u in DEFAULT_TAGS)

def session_text(session: dict) -> str:
    time_str  = f" в <b>{session['time']}</b>" if session.get("time") else ""
    yes_names = session.get("yes_names", [])
    no_names  = session.get("no_names", [])
    return (
        f"⚔️ <b>{session['caller']} зовёт в Dota 2{time_str}!</b>\n\n"
        f"👥 {all_mentions()}\n\n"
        f"✅ {len(yes_names)}  —  {', '.join(yes_names) or '—'}\n"
        f"❌ {len(no_names)}  —  {', '.join(no_names) or '—'}"
    )

def vote_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Иду!", callback_data="vote_yes"),
        InlineKeyboardButton("❌ Не могу", callback_data="vote_no"),
    ]])

# ─── API ─────────────────────────────────────────────────────────────────────

async def fetch_hero_names(session: aiohttp.ClientSession):
    global HERO_NAMES
    if HERO_NAMES:
        return
    try:
        async with session.get("https://api.opendota.com/api/heroes", timeout=aiohttp.ClientTimeout(total=10)) as r:
            heroes = await r.json()
            HERO_NAMES = {h["id"]: h["localized_name"] for h in heroes}
            logger.info(f"Loaded {len(HERO_NAMES)} heroes")
    except Exception as e:
        logger.warning(f"Could not load hero names: {e}")

async def fetch_item_names(session: aiohttp.ClientSession):
    global ITEM_NAMES
    if ITEM_NAMES:
        return
    try:
        async with session.get("https://api.opendota.com/api/constants/items", timeout=aiohttp.ClientTimeout(total=10)) as r:
            data = await r.json()
            ITEM_NAMES = {v["id"]: v["dname"] for k, v in data.items() if "id" in v and "dname" in v}
            logger.info(f"Loaded {len(ITEM_NAMES)} items")
    except Exception as e:
        logger.warning(f"Could not load item names: {e}")

async def get_last_match_id(session: aiohttp.ClientSession, steam_id: str) -> str | None:
    try:
        account_id = int(steam_id) - 76561197960265728
        url = (
            f"https://api.steampowered.com/IDOTA2Match_570/GetMatchHistory/v1/"
            f"?key={STEAM_API_KEY}&account_id={account_id}&matches_requested=1"
        )
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            data = await r.json()
            matches = data.get("result", {}).get("matches", [])
            if matches:
                return str(matches[0]["match_id"])
    except Exception as e:
        logger.warning(f"get_last_match_id error: {e}")
    return None

async def get_match_details(session: aiohttp.ClientSession, match_id: str) -> dict | None:
    # OpenDota первым — там есть предметы и статы
    try:
        async with session.get(f"https://api.opendota.com/api/matches/{match_id}", timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status == 200:
                data = await r.json()
                if data.get("match_id") or data.get("players"):
                    logger.info(f"Got match {match_id} from OpenDota")
                    return data
    except Exception as e:
        logger.warning(f"OpenDota match details error: {e}")
    # Steam API fallback
    try:
        url = f"https://api.steampowered.com/IDOTA2Match_570/GetMatchDetails/v1/?key={STEAM_API_KEY}&match_id={match_id}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
            data = await r.json()
            result = data.get("result", {})
            if result.get("match_id"):
                logger.info(f"Got match {match_id} from Steam API")
                return result
    except Exception as e:
        logger.warning(f"Steam match details error: {e}")
    return None

async def request_parse(session: aiohttp.ClientSession, match_id: str):
    try:
        async with session.post(f"https://api.opendota.com/api/request/{match_id}", timeout=aiohttp.ClientTimeout(total=10)) as r:
            logger.info(f"Requested parse for {match_id}: {r.status}")
    except Exception as e:
        logger.warning(f"Parse request error: {e}")

def get_items(p: dict) -> str:
    slots = ["item_0","item_1","item_2","item_3","item_4","item_5"]
    items = []
    for slot in slots:
        iid = p.get(slot, 0)
        if iid and iid != 0:
            name = ITEM_NAMES.get(iid, f"item#{iid}")
            items.append(name)
    return ", ".join(items) if items else "—"

def get_rank(rank_tier) -> str:
    if not rank_tier:
        return "Uncalibrated"
    medals = {1:"Herald",2:"Guardian",3:"Crusader",4:"Archon",5:"Legend",6:"Ancient",7:"Divine",8:"Immortal"}
    tier = rank_tier // 10
    star = rank_tier % 10
    name = medals.get(tier, "?")
    if tier == 8:
        return "Immortal"
    return f"{name} {star}⭐"

def get_position(team_slot: int) -> str:
    positions = {0:"Pos 1 (Carry)", 1:"Pos 2 (Mid)", 2:"Pos 3 (Offlane)", 3:"Pos 4 (Soft Support)", 4:"Pos 5 (Hard Support)"}
    return positions.get(team_slot, f"Pos {team_slot+1}")

def format_match_message(match: dict) -> str:
    players_data = match.get("players", [])
    duration_min = match.get("duration", 0) // 60
    duration_sec = match.get("duration", 0) % 60
    radiant_win  = match.get("radiant_win", False)
    steam_to_tg  = {v: k for k, v in PLAYERS.items()}
    # account_id -> tg username (32-bit form)
    acct_to_tg   = {int(v) - 76561197960265728: k for k, v in PLAYERS.items()}

    radiant = []
    dire    = []
    our_team_radiant = None
    our_players = []

    for p in players_data:
        account_id = p.get("account_id", 0)
        steam64    = str(account_id + 76561197960265728)
        slot       = p.get("player_slot", 0)
        is_radiant = slot < 128
        hero       = HERO_NAMES.get(p.get("hero_id", 0), f"Hero#{p.get('hero_id',0)}")
        kills      = p.get("kills", 0)
        deaths     = p.get("deaths", 0)
        assists    = p.get("assists", 0)
        gpm        = p.get("gold_per_min", 0)
        xpm        = p.get("xp_per_min", 0)
        dmg        = p.get("hero_damage", 0)
        lh         = p.get("last_hits", 0)
        items_str  = get_items(p)
        team_slot  = p.get("team_slot", 0)

        tg_name = acct_to_tg.get(account_id) if account_id and account_id != 4294967295 else None

        if tg_name:
            our_players.append(tg_name)
            if our_team_radiant is None:
                our_team_radiant = is_radiant
            rank    = get_rank(p.get("rank_tier"))
            pos     = get_position(p.get("team_slot", 0))
            entry = (
                f"  @{tg_name} — <b>{hero}</b>\n"
                f"    🏅 {rank} | {pos}\n"
                f"    📊 {kills}/{deaths}/{assists} | GPM: {gpm} | XPM: {xpm}\n"
                f"    ⚔️ Урон: {dmg:,} | LH: {lh}\n"
                f"    🎒 {items_str}"
            )
        else:
            entry = f"  ? — <b>{hero}</b> ({kills}/{deaths}/{assists})"

        if is_radiant:
            radiant.append(entry)
        else:
            dire.append(entry)

    if our_team_radiant is None:
        our_team_radiant = True

    won = (radiant_win and our_team_radiant) or (not radiant_win and not our_team_radiant)
    result_emoji = "🏆 ПОБЕДА!" if won else "💀 ПОРАЖЕНИЕ"

    lines = [
        result_emoji,
        f"⏱ Длительность: {duration_min}:{duration_sec:02d}",
        f"🎮 Матч #{match.get('match_id', '?')}",
        "",
        "🟢 Radiant:",
    ]
    lines.extend(radiant)
    lines.append("")
    lines.append("🔴 Dire:")
    lines.extend(dire)

    if our_players:
        lines.append("")
        lines.append(f"🛡 Наши: {', '.join('@'+p for p in our_players)}")

    return "\n".join(lines)

def count_our_players(match: dict) -> int:
    acct_to_tg = {int(v) - 76561197960265728: k for k, v in PLAYERS.items()}
    count = 0
    for p in match.get("players", []):
        account_id = p.get("account_id", 0)
        if account_id and account_id != 4294967295 and account_id in acct_to_tg:
            count += 1
    return count

# ─── мониторинг ──────────────────────────────────────────────────────────────

async def monitor_matches(app):
    global last_known_match
    await asyncio.sleep(10)

    async with aiohttp.ClientSession() as session:
        await fetch_hero_names(session)
        await fetch_item_names(session)

        mid = await get_last_match_id(session, HOST_ID)
        last_known_match = mid
        logger.info(f"Monitor started. Last match: {last_known_match}")

        while True:
            try:
                await asyncio.sleep(120)

                mid = await get_last_match_id(session, HOST_ID)
                if not mid or mid == last_known_match or mid in reported_matches:
                    logger.info(f"No new match (last={mid})")
                    continue

                logger.info(f"NEW match: {mid}")
                last_known_match = mid

                # Запрашиваем парсинг OpenDota
                await request_parse(session, mid)
                await asyncio.sleep(60)  # ждём парсинг

                match = await get_match_details(session, mid)
                if not match:
                    logger.warning(f"Could not get match {mid}")
                    continue

                our_count = count_our_players(match)
                logger.info(f"Match {mid}: {our_count} of our players")

                if our_count < 2:
                    logger.info("Less than 2 our players, skipping")
                    continue

                msg = format_match_message(match)
                if msg:
                    reported_matches.add(mid)
                    await app.bot.send_message(chat_id=ALLOWED_CHAT_ID, text=msg, parse_mode="HTML")
                    logger.info(f"Reported match {mid}")

            except Exception as e:
                logger.error(f"Monitor error: {e}")
                await asyncio.sleep(30)

# ─── команды ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update): return
    await update.message.reply_text(
        "🎮 <b>Dota 2 Bot</b>\n\n"
        "/dota — позвать всех прямо сейчас\n"
        "/schedule 21:00 — запланировать игру\n"
        "/lastmatch — последний матч\n"
        "/roulette — кто аутист?\n"
        "/players — список игроков\n"
        "/cancel — отменить сессию",
        parse_mode="HTML",
    )

async def cmd_players(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update): return
    lines = "\n".join(f"{i+1}. @{u}" for i, u in enumerate(DEFAULT_TAGS))
    await update.message.reply_text(f"🎮 <b>Игроки:</b>\n{lines}", parse_mode="HTML")

async def _start_session(update: Update, time_str: str | None):
    if not await group_only(update): return
    chat_id = update.effective_chat.id
    caller  = update.effective_user
    sessions[chat_id] = {
        "caller":    caller.full_name or caller.username or str(caller.id),
        "caller_id": caller.id,
        "yes_names": [],
        "no_names":  [],
        "yes_ids":   set(),
        "no_ids":    set(),
        "time": time_str,
    }
    await update.message.reply_text(all_mentions())
    await update.message.reply_text(session_text(sessions[chat_id]), parse_mode="HTML", reply_markup=vote_kb())

async def cmd_dota(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await _start_session(update, None)

async def cmd_schedule(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    time_str = " ".join(ctx.args) if ctx.args else None
    if not time_str:
        await update.message.reply_text("Использование: /schedule 21:00")
        return
    await _start_session(update, time_str)

async def cmd_cancel(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update): return
    chat_id = update.effective_chat.id
    if chat_id in sessions:
        sessions.pop(chat_id)
        await update.message.reply_text("🚫 Сессия отменена.")
    else:
        await update.message.reply_text("Нет активной сессии.")

async def cmd_roulette(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update): return
    victim = "@" + random.choice(DEFAULT_TAGS)
    await update.message.reply_text(
        f"🎰 Рулетка крутится...\n\n🤡 <b>Аутист дня:</b> {victim}",
        parse_mode="HTML",
    )

async def cmd_lastmatch(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update): return
    user = update.effective_user
    username = (user.username or "").lower()

    # Ищем steam ID того кто написал команду
    steam_id = TG_TO_STEAM.get(username)
    if not steam_id:
        await update.message.reply_text(
            f"❌ @{user.username or user.first_name} не найден в списке игроков.\n"
            f"Список: {', '.join('@'+u for u in PLAYERS)}"
        )
        return

    await update.message.reply_text(f"🔍 Ищу последний матч @{username}...")
    async with aiohttp.ClientSession() as session:
        await fetch_hero_names(session)
        await fetch_item_names(session)
        mid = await get_last_match_id(session, steam_id)
        if not mid:
            await update.message.reply_text("❌ Не удалось найти матч.")
            return
        await request_parse(session, mid)
        await asyncio.sleep(3)
        match = await get_match_details(session, mid)
        if not match:
            await update.message.reply_text("❌ Не удалось получить детали матча.")
            return
        our_count = count_our_players(match)
        if our_count < 1:
            await update.message.reply_text("😕 Никого из наших в этом матче не найдено.")
            return
        msg = format_match_message(match)
        if msg:
            await update.message.reply_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_text("😕 Не удалось сформировать сообщение.")

async def on_vote(update: Update, _: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_chat.type not in ("group", "supergroup"): return
    chat_id = update.effective_chat.id
    user    = update.effective_user
    session = sessions.get(chat_id)
    if not session:
        await query.answer("Сессия уже завершена.", show_alert=True)
        return

    uid  = user.id
    name = user.full_name or user.username or str(uid)

    if query.data == "vote_yes":
        if uid not in session["yes_ids"]:
            session["yes_ids"].add(uid)
            session["yes_names"].append(name)
        if uid in session["no_ids"]:
            session["no_ids"].discard(uid)
            session["no_names"] = [n for n in session["no_names"] if n != name]
    else:
        if uid not in session["no_ids"]:
            session["no_ids"].add(uid)
            session["no_names"].append(name)
        if uid in session["yes_ids"]:
            session["yes_ids"].discard(uid)
            session["yes_names"] = [n for n in session["yes_names"] if n != name]

    await query.edit_message_text(session_text(session), parse_mode="HTML", reply_markup=vote_kb())

async def post_init(app):
    asyncio.create_task(monitor_matches(app))

def main():
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("help",      cmd_start))
    app.add_handler(CommandHandler("players",   cmd_players))
    app.add_handler(CommandHandler("dota",      cmd_dota))
    app.add_handler(CommandHandler("schedule",  cmd_schedule))
    app.add_handler(CommandHandler("cancel",    cmd_cancel))
    app.add_handler(CommandHandler("roulette",  cmd_roulette))
    app.add_handler(CommandHandler("lastmatch", cmd_lastmatch))
    app.add_handler(CallbackQueryHandler(on_vote, pattern="^vote_"))
    logger.info("🎮 ErniFidBot запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
