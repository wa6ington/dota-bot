#!/usr/bin/env python3
"""
🎮 Dota 2 Telegram Bot — @ErniFidBot
Следит за матчами и постит результаты в группу
"""

import logging
import asyncio
import aiohttp
import random
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Конфиг ──────────────────────────────────────────────────────────────────

TOKEN         = "8356191098:AAFu3axbr5OaEDlYyRUK_bhNKj1Zty8Za8Y"
STEAM_API_KEY = "F25FE222BDDD5D2687073BAEF0D8CBB8"
ALLOWED_CHAT_ID = -1003719823975

# Игроки: tg_username -> steam_id64
PLAYERS = {
    "limon1705":      "76561199015459521",
    "wa6ingtonn":     "76561198312814207",
    "areembee":       "76561198385353313",
    "Tawer4K":        "76561198841600203",
    "neskvikcpivom2": "76561199004933239",
}

# ─── Фильтр ──────────────────────────────────────────────────────────────────

async def group_only(update: Update) -> bool:
    return update.effective_chat.id == ALLOWED_CHAT_ID

# ─── Хранилище ───────────────────────────────────────────────────────────────

registered: dict[int, dict[int, str]] = {}
sessions:   dict[int, dict] = {}

# match_id -> уже отправлено (чтобы не дублировать)
reported_matches: set[str] = set()

# последний известный match_id для каждого steam_id
last_match: dict[str, str] = {}

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

# ─── Steam / OpenDota API ─────────────────────────────────────────────────────

HERO_NAMES: dict[int, str] = {}  # hero_id -> локализованное имя

async def fetch_hero_names(session: aiohttp.ClientSession):
    global HERO_NAMES
    try:
        url = "https://api.opendota.com/api/heroes"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            heroes = await r.json()
            HERO_NAMES = {h["id"]: h["localized_name"] for h in heroes}
            logger.info(f"Loaded {len(HERO_NAMES)} heroes")
    except Exception as e:
        logger.warning(f"Could not load hero names: {e}")

async def get_last_match_id(session: aiohttp.ClientSession, steam_id: str) -> str | None:
    """Получить ID последнего матча игрока через Steam API."""
    try:
        # Конвертируем steam64 -> account_id (32-bit)
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
        logger.warning(f"get_last_match_id error for {steam_id}: {e}")
    return None

async def get_match_details(session: aiohttp.ClientSession, match_id: str) -> dict | None:
    """Получить детали матча через OpenDota API."""
    try:
        url = f"https://api.opendota.com/api/matches/{match_id}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status == 200:
                return await r.json()
    except Exception as e:
        logger.warning(f"get_match_details error for {match_id}: {e}")
    return None

def format_match_message(match: dict, our_steam_ids: set[str]) -> str:
    """Форматируем сообщение о матче."""
    players_data = match.get("players", [])
    duration_min = match.get("duration", 0) // 60
    duration_sec = match.get("duration", 0) % 60
    radiant_win  = match.get("radiant_win", False)

    # Находим наших игроков в матче
    our_players = []
    our_team = None

    steam_to_tg = {v: k for k, v in PLAYERS.items()}

    for p in players_data:
        account_id = p.get("account_id", 0)
        steam64 = str(account_id + 76561197960265728)
        if steam64 in our_steam_ids:
            tg_name = steam_to_tg.get(steam64, steam64)
            hero_id = p.get("hero_id", 0)
            hero    = HERO_NAMES.get(hero_id, f"Hero#{hero_id}")
            kills   = p.get("kills", 0)
            deaths  = p.get("deaths", 0)
            assists = p.get("assists", 0)
            slot    = p.get("player_slot", 0)
            is_radiant = slot < 128
            if our_team is None:
                our_team = is_radiant
            our_players.append({
                "tg": tg_name,
                "hero": hero,
                "kda": f"{kills}/{deaths}/{assists}",
                "is_radiant": is_radiant,
            })

    if not our_players:
        return ""

    # Победили или нет
    our_radiant = our_players[0]["is_radiant"]
    won = (radiant_win and our_radiant) or (not radiant_win and not our_radiant)
    result_emoji = "🏆 ПОБЕДА!" if won else "💀 ПОРАЖЕНИЕ"

    lines = [
        f"{result_emoji}",
        f"⏱ Длительность: {duration_min}:{duration_sec:02d}",
        f"🎮 Матч #{match.get('match_id', '?')}",
        "",
        "👤 Наши игроки:",
    ]

    for p in our_players:
        lines.append(f"  @{p['tg']} — <b>{p['hero']}</b> ({p['kda']})")

    return "\n".join(lines)

# ─── Фоновый мониторинг матчей ────────────────────────────────────────────────

async def monitor_matches(app):
    """Каждые 2 минуты проверяем новые матчи у всех игроков."""
    await asyncio.sleep(10)  # небольшая задержка после старта

    async with aiohttp.ClientSession() as session:
        # Загружаем названия героев
        await fetch_hero_names(session)

        # Инициализируем last_match только для wa6ingtonn (публичный профиль)
        logger.info("Initializing last match ID for wa6ingtonn...")
        host_id = PLAYERS["wa6ingtonn"]
        mid = await get_last_match_id(session, host_id)
        if mid:
            last_match[host_id] = mid
            logger.info(f"  wa6ingtonn: last match = {mid}")
        else:
            logger.warning(f"  wa6ingtonn: NO MATCH FOUND — check Steam ID or profile privacy")

        logger.info("Match monitor started!")

        while True:
            try:
                await asyncio.sleep(120)  # проверяем каждые 2 минуты

                # Собираем новые матчи
                new_matches: dict[str, list[str]] = {}  # match_id -> [steam_ids]

                for tg, steam_id in PLAYERS.items():
                    mid = await get_last_match_id(session, steam_id)
                    await asyncio.sleep(0.5)

                    if not mid:
                        logger.warning(f"  [{tg}] no match returned from Steam API")
                        continue
                    if mid == last_match.get(steam_id):
                        logger.info(f"  [{tg}] no new match (last={mid})")
                        continue
                    if mid in reported_matches:
                        last_match[steam_id] = mid
                        continue

                    # Новый матч!
                    logger.info(f"  [{tg}] NEW match = {mid}!")
                    last_match[steam_id] = mid
                    new_matches.setdefault(mid, []).append(steam_id)

                # Обрабатываем новые матчи где играли 2+ наших игрока
                for match_id, steam_ids in new_matches.items():
                    if match_id in reported_matches:
                        continue

                    # Ждём чуть дольше чтобы OpenDota обработал матч
                    await asyncio.sleep(30)

                    match = await get_match_details(session, match_id)
                    if not match:
                        continue

                    # Проверяем сколько наших в этом матче
                    our_in_match = set()
                    for p in match.get("players", []):
                        account_id = p.get("account_id", 0)
                        steam64 = str(account_id + 76561197960265728)
                        if steam64 in PLAYERS.values():
                            our_in_match.add(steam64)

                    if len(our_in_match) < 4:
                        continue  # меньше 2 наших — не репортим

                    msg = format_match_message(match, our_in_match)
                    if msg:
                        reported_matches.add(match_id)
                        await app.bot.send_message(
                            chat_id=ALLOWED_CHAT_ID,
                            text=msg,
                            parse_mode="HTML",
                        )
                        logger.info(f"Reported match {match_id} with {len(our_in_match)} players")

            except Exception as e:
                logger.error(f"Monitor error: {e}")
                await asyncio.sleep(30)

# ─── Команды ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update): return
    await update.message.reply_text(
        "🎮 <b>Dota 2 Bot</b>\n\n"
        "/dota — позвать всех прямо сейчас\n"
        "/schedule 21:00 — запланировать игру\n"
        "/reg — добавить себя в список\n"
        "/unreg — выйти из списка\n"
        "/players — список зарегистрированных\n"
        "/roulette — кто аутист?\n"
        "/cancel — отменить сессию\n\n"
        "🔍 Бот автоматически следит за матчами и постит результаты!",
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
    await update.message.reply_text(
        f"🎮 <b>Игроки отслеживаемые ботом:</b>\n{lines}",
        parse_mode="HTML",
    )

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
    await update.message.reply_text(
        session_text(sessions[chat_id], chat_id),
        parse_mode="HTML",
        reply_markup=vote_kb(),
    )

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
    await update.message.reply_text(
        f"🎰 Рулетка крутится...\n\n🤡 <b>Аутист дня:</b> {victim}",
        parse_mode="HTML",
    )

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
    get_registered(chat_id).setdefault(
        user.id, user.full_name or user.username or str(user.id)
    )
    if query.data == "vote_yes":
        session["yes"].add(user.id)
        session["no"].discard(user.id)
    else:
        session["no"].add(user.id)
        session["yes"].discard(user.id)
    await query.edit_message_text(
        session_text(session, chat_id),
        parse_mode="HTML",
        reply_markup=vote_kb(),
    )

# ─── Main ─────────────────────────────────────────────────────────────────────

async def post_init(app):
    asyncio.create_task(monitor_matches(app))

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
    app.add_handler(CommandHandler("roulette", cmd_roulette))
    app.add_handler(CallbackQueryHandler(on_vote, pattern="^vote_"))
    logger.info("🎮 ErniFidBot запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
