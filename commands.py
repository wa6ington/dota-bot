import logging
import asyncio
import random
import aiohttp

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import ALLOWED_CHAT_ID, PLAYERS, DEFAULT_TAGS, TG_TO_STEAM, HOST_ID
from steam import fetch_hero_names, fetch_item_names, get_last_match_id, get_match_details, request_parse, count_our_players
from formatter import format_match_message

logger = logging.getLogger(__name__)

sessions: dict[int, dict] = {}


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

# ─── команды ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update): return
    await update.message.reply_text(
        "🎮 <b>Dota 2 Bot</b>\n\n"
        "/dota — позвать всех прямо сейчас\n"
        "/schedule 21:00 — запланировать игру\n"
        "/lastmatch — твой последний матч\n"
        "/analyze 123456 — разбор любого матча\n"
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
    user     = update.effective_user
    username = (user.username or "").lower()

    steam_id = TG_TO_STEAM.get(username)
    if not steam_id:
        await update.message.reply_text(
            f"❌ @{user.username or user.first_name} не в списке игроков.\n"
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
        msg = format_match_message(match)
        if msg:
            await update.message.reply_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_text("😕 Не удалось сформировать сообщение.")

async def cmd_analyze(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update): return
    if not ctx.args:
        await update.message.reply_text("Использование: /analyze 8726314725")
        return
    match_id = ctx.args[0].strip()
    if not match_id.isdigit():
        await update.message.reply_text("❌ Неверный match_id. Пример: /analyze 8726314725")
        return
    await update.message.reply_text(f"🔍 Загружаю матч #{match_id}...")
    async with aiohttp.ClientSession() as session:
        await fetch_hero_names(session)
        await fetch_item_names(session)
        await request_parse(session, match_id)
        await asyncio.sleep(3)
        match = await get_match_details(session, match_id)
        if not match:
            await update.message.reply_text("❌ Матч не найден. Попробуй позже.")
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
