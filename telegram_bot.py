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

TOKEN         = "8356191098:AAFu3axbr5OaEDlYyRUK_bhNKj1Zty8Za8Y"
STEAM_API_KEY = "F25FE222BDDD5D2687073BAEF0D8CBB8"
ALLOWED_CHAT_ID = -1003719823975

PLAYERS = {
    "limon1705":      "76561199015459521",
    "wa6ingtonn":     "76561198312814207",
    "areembee":       "76561198385353313",
    "Tawer4K":        "76561198841600203",
    "neskvikcpivom2": "76561199004933239",
}

registered: dict[int, dict[int, str]] = {}
sessions:   dict[int, dict] = {}
reported_matches: set[str] = set()
last_match: dict[str, str] = {}
HERO_NAMES: dict[int, str] = {}

async def group_only(update: Update) -> bool:
    return update.effective_chat.id == ALLOWED_CHAT_ID

def get_registered(chat_id: int) -> dict[int, str]:
    return registered.setdefault(chat_id, {})

def default_mentions() -> str:
    return " ".join(f"@{u}" for u in PLAYERS)

def registered_mentions(chat_id: int) -> str:
    pool = get_registered(chat_id)
    return " ".join(f'<a href="tg://user?id={uid}">{name}</a>' for uid, name in pool.items())

def session_text(session: dict, chat_id: int) -> str:
    pool = get_registered(chat_id)
    time_str = f" в <b>{session['time']}</b>" if session.get("time") else ""
    tagged = registered_mentions(chat_id) or default_mentions()
    yes_names = [pool.get(uid, f"user{uid}") for uid in session["yes"]]
    no_names  = [pool.get(uid, f"user{uid}") for uid in session["no"]]
    return (
        f"⚔️ <b>{session['caller']} зовёт в Dota 2{time_str}!</b>\n\n"
        f"👥 {tagged}\n\n"
        f"✅ {len(session['yes'])}  —  {', '.join(yes_names) or '—'}\n"
        f"❌ {len(session['no'])}  —  {', '.join(no_names) or '—'}"
    )

def vote_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Иду!", callback_data="vote_yes"),
        InlineKeyboardButton("❌ Не могу", callback_data="vote_no"),
    ]])

async def fetch_hero_names(session: aiohttp.ClientSession):
    global HERO_NAMES
    try:
        async with session.get("https://api.opendota.com/api/heroes", timeout=aiohttp.ClientTimeout(total=10)) as r:
            heroes = await r.json()
            HERO_NAMES = {h["id"]: h["localized_name"] for h in heroes}
            logger.info(f"Loaded {len(HERO_NAMES)} heroes")
    except Exception as e:
        logger.warning(f"Could not load hero names: {e}")

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
                return str(matches[0]["match_id"]), matches[0].get("players", [])
    except Exception as e:
        logger.warning(f"get_last_match_id error: {e}")
    return None, []

async def get_match_history_players(session: aiohttp.ClientSession, steam_id: str, match_id: str) -> list:
    """Получить список игроков матча из GetMatchHistory (hero_id есть, K/D нет)"""
    try:
        account_id = int(steam_id) - 76561197960265728
        url = (
            f"https://api.steampowered.com/IDOTA2Match_570/GetMatchHistory/v1/"
            f"?key={STEAM_API_KEY}&account_id={account_id}&matches_requested=10"
        )
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            data = await r.json()
            matches = data.get("result", {}).get("matches", [])
            for m in matches:
                if str(m["match_id"]) == str(match_id):
                    return m.get("players", [])
    except Exception as e:
        logger.warning(f"get_match_history_players error: {e}")
    return []

async def get_match_details(session: aiohttp.ClientSession, match_id: str) -> dict | None:
    # Сначала пробуем Steam API (быстрее, не требует парсинга)
    try:
        url = f"https://api.steampowered.com/IDOTA2Match_570/GetMatchDetails/v1/?key={STEAM_API_KEY}&match_id={match_id}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
            data = await r.json()
            result = data.get("result", {})
            if result.get("match_id"):
                logger.info(f"Got match {match_id} from Steam API")
                return result
    except Exception as e:
        logger.warning(f"Steam get_match_details error: {e}")
    # Фолбек на OpenDota
    try:
        async with session.get(f"https://api.opendota.com/api/matches/{match_id}", timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status == 200:
                logger.info(f"Got match {match_id} from OpenDota")
                return await r.json()
    except Exception as e:
        logger.warning(f"OpenDota get_match_details error: {e}")
    return None

def format_match_message(match: dict, our_steam_ids: set[str], history_players: list = None) -> str:
    players_data = match.get("players", [])
    duration_min = match.get("duration", 0) // 60
    duration_sec = match.get("duration", 0) % 60
    radiant_win  = match.get("radiant_win", False)
    steam_to_tg  = {v: k for k, v in PLAYERS.items()}

    # Строим словарь hero_id по account_id из истории (для приватных игроков)
    history_hero = {}
    if history_players:
        for p in history_players:
            history_hero[p.get("account_id")] = p.get("hero_id", 0)

    radiant = []
    dire    = []

    for p in players_data:
        account_id = p.get("account_id", 0)
        steam64    = str(account_id + 76561197960265728)
        slot       = p.get("player_slot", 0)
        is_radiant = slot < 128
        hero_id    = p.get("hero_id") or history_hero.get(account_id, 0)
        hero       = HERO_NAMES.get(hero_id, f"Hero#{hero_id}")

        if steam64 in our_steam_ids and account_id != 4294967295:
            # Знаем кто это — показываем с K/D/A
            tg_name = steam_to_tg.get(steam64, "?")
            kills   = p.get("kills", 0)
            deaths  = p.get("deaths", 0)
            assists = p.get("assists", 0)
            entry   = f"  @{tg_name} — <b>{hero}</b> ({kills}/{deaths}/{assists})"
        elif account_id != 4294967295:
            # Знаем account_id но не наш — может быть наш с приватным профилем
            tg_name = steam_to_tg.get(steam64, None)
            if tg_name:
                kills   = p.get("kills", 0)
                deaths  = p.get("deaths", 0)
                assists = p.get("assists", 0)
                entry   = f"  @{tg_name} — <b>{hero}</b> ({kills}/{deaths}/{assists})"
            else:
                entry = f"  ? — <b>{hero}</b>"
        else:
            # Приватный — только герой
            entry = f"  ? — <b>{hero}</b>"

        if is_radiant:
            radiant.append(entry)
        else:
            dire.append(entry)

    if not radiant and not dire:
        return ""

    # Определяем нашу команду
    our_team_radiant = any(
        str(p.get("account_id", 0) + 76561197960265728) in our_steam_ids and p.get("player_slot", 0) < 128
        for p in players_data
    )
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

    return "\n".join(lines)

async def monitor_matches(app):
    await asyncio.sleep(10)

    async with aiohttp.ClientSession() as session:
        await fetch_hero_names(session)

        HOST_ID = PLAYERS["wa6ingtonn"]
        logger.info("Initializing last match ID for wa6ingtonn...")
        result = await get_last_match_id(session, HOST_ID)
        mid = result[0] if result else None
        if mid:
            last_match[HOST_ID] = mid
            logger.info(f"  wa6ingtonn: last match = {mid}")
        else:
            logger.warning("  wa6ingtonn: NO MATCH FOUND")

        logger.info("Match monitor started!")

        while True:
            try:
                await asyncio.sleep(120)

                result = await get_last_match_id(session, HOST_ID)
                mid = result[0] if result else None

                if not mid:
                    logger.warning("No match returned for wa6ingtonn")
                    continue

                if mid == last_match.get(HOST_ID):
                    logger.info(f"No new match (last={mid})")
                    continue

                if mid in reported_matches:
                    last_match[HOST_ID] = mid
                    continue

                logger.info(f"NEW match for wa6ingtonn: {mid}")
                last_match[HOST_ID] = mid

                await asyncio.sleep(30)

                match = await get_match_details(session, mid)
                if not match:
                    logger.warning(f"Could not get details for match {mid}")
                    continue

                our_in_match = set()
                for p in match.get("players", []):
                    steam64 = str(p.get("account_id", 0) + 76561197960265728)
                    if steam64 in PLAYERS.values():
                        our_in_match.add(steam64)

                logger.info(f"Match {mid}: found {len(our_in_match)} of our players")

                if len(our_in_match) < 2:
                    logger.info(f"Only {len(our_in_match)} players, skipping (need 2+)")
                    continue

                msg = format_match_message(match, our_in_match)
                if msg:
                    reported_matches.add(mid)
                    await app.bot.send_message(
                        chat_id=ALLOWED_CHAT_ID,
                        text=msg,
                        parse_mode="HTML",
                    )
                    logger.info(f"Reported match {mid} with {len(our_in_match)} players")

            except Exception as e:
                logger.error(f"Monitor error: {e}")
                await asyncio.sleep(30)

async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update): return
    await update.message.reply_text(
        "🎮 <b>Dota 2 Bot</b>\n\n"
        "/dota — позвать всех прямо сейчас\n"
        "/schedule 21:00 — запланировать игру\n"
        "/reg — добавить себя в список\n"
        "/unreg — выйти из списка\n"
        "/players — список игроков\n"
        "/roulette — кто аутист?\n"
        "/cancel — отменить сессию\n\n"
        "🔍 Бот следит за матчами и постит результаты!",
        parse_mode="HTML",
    )

async def cmd_reg(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update): return
    user = update.effective_user
    chat_id = update.effective_chat.id
    pool = get_registered(chat_id)
    pool[user.id] = user.full_name or user.username or str(user.id)
    await update.message.reply_text(
        f'✅ <a href="tg://user?id={user.id}">{pool[user.id]}</a> добавлен в список!',
        parse_mode="HTML",
    )

async def cmd_unreg(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update): return
    user = update.effective_user
    pool = get_registered(update.effective_chat.id)
    if user.id in pool:
        name = pool.pop(user.id)
        await update.message.reply_text(f"👋 {name} удалён из списка.")
    else:
        await update.message.reply_text("Тебя нет в списке.")

async def cmd_players(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update): return
    lines = "\n".join(f"{i+1}. @{u}" for i, u in enumerate(PLAYERS))
    await update.message.reply_text(f"🎮 <b>Игроки:</b>\n{lines}", parse_mode="HTML")

async def _start_session(update: Update, time_str: str | None):
    if not await group_only(update): return
    chat_id = update.effective_chat.id
    caller  = update.effective_user
    sessions[chat_id] = {
        "caller":    caller.full_name or caller.username or str(caller.id),
        "caller_id": caller.id,
        "yes": set(),
        "no":  set(),
        "time": time_str,
    }
    ping = registered_mentions(chat_id) or default_mentions()
    await update.message.reply_text(ping, parse_mode="HTML")
    await update.message.reply_text(session_text(sessions[chat_id], chat_id), parse_mode="HTML", reply_markup=vote_kb())

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
    pool = get_registered(update.effective_chat.id)
    if pool:
        uid, name = random.choice(list(pool.items()))
        victim = f'<a href="tg://user?id={uid}">{name}</a>'
    else:
        victim = "@" + random.choice(list(PLAYERS.keys()))
    await update.message.reply_text(f"🎰 Рулетка крутится...\n\n🤡 <b>Аутист дня:</b> {victim}", parse_mode="HTML")


async def cmd_lastmatch(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update): return
    await update.message.reply_text("🔍 Ищу последний матч...", parse_mode="HTML")
    async with aiohttp.ClientSession() as session:
        await fetch_hero_names(session)
        HOST_ID = PLAYERS["wa6ingtonn"]
        result = await get_last_match_id(session, HOST_ID)
        mid = result[0] if result else None
        if not mid:
            await update.message.reply_text("❌ Не удалось найти матч.")
            return
        match = await get_match_details(session, mid)
        if not match:
            await update.message.reply_text("❌ Не удалось получить детали матча.")
            return
        our_in_match = set()
        for p in match.get("players", []):
            steam64 = str(p.get("account_id", 0) + 76561197960265728)
            if steam64 in PLAYERS.values():
                our_in_match.add(steam64)
        if not our_in_match:
            await update.message.reply_text("😕 Никого из наших в последнем матче не найдено.")
            return
        msg = format_match_message(match, our_in_match)
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
    get_registered(chat_id).setdefault(user.id, user.full_name or user.username or str(user.id))
    if query.data == "vote_yes":
        session["yes"].add(user.id)
        session["no"].discard(user.id)
    else:
        session["no"].add(user.id)
        session["yes"].discard(user.id)
    await query.edit_message_text(session_text(session, chat_id), parse_mode="HTML", reply_markup=vote_kb())

async def post_init(app):
    asyncio.create_task(monitor_matches(app))
    asyncio.create_task(send_last_match_on_start(app))

async def send_last_match_on_start(app):
    await asyncio.sleep(15)  # ждём пока бот поднимется
    try:
        async with aiohttp.ClientSession() as session:
            await fetch_hero_names(session)
            HOST_ID = PLAYERS["wa6ingtonn"]
            result = await get_last_match_id(session, HOST_ID)
            mid = result[0] if result else None
            if not mid:
                return
            match = await get_match_details(session, mid)
            if not match:
                return
            our_in_match = set()
            for p in match.get("players", []):
                steam64 = str(p.get("account_id", 0) + 76561197960265728)
                if steam64 in PLAYERS.values():
                    our_in_match.add(steam64)
            if not our_in_match:
                return
            msg = format_match_message(match, our_in_match)
            if msg:
                await app.bot.send_message(
                    chat_id=ALLOWED_CHAT_ID,
                    text="🚀 <b>Бот запущен! Последний матч:</b>\n\n" + msg,
                    parse_mode="HTML",
                )
                logger.info(f"Sent last match on startup: {mid}")
    except Exception as e:
        logger.error(f"send_last_match_on_start error: {e}")

def main():
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("help",     cmd_start))
    app.add_handler(CommandHandler("reg",      cmd_reg))
    app.add_handler(CommandHandler("unreg",    cmd_unreg))
    app.add_handler(CommandHandler("players",  cmd_players))
    app.add_handler(CommandHandler("dota",     cmd_dota))
    app.add_handler(CommandHandler("schedule", cmd_schedule))
    app.add_handler(CommandHandler("cancel",   cmd_cancel))
    app.add_handler(CommandHandler("roulette",   cmd_roulette))
    app.add_handler(CommandHandler("lastmatch",  cmd_lastmatch))
    app.add_handler(CallbackQueryHandler(on_vote, pattern="^vote_"))
    logger.info("🎮 ErniFidBot запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
