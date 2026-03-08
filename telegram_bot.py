#!/usr/bin/env python3
"""
🎮 Dota 2 Telegram Bot — @ErniFidBot

Установка:
    pip install "python-telegram-bot==20.*"

Запуск:
    python telegram_bot.py
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── Конфиг ──────────────────────────────────────────────────────────────────

TOKEN = "8356191098:AAFu3axbr5OaEDlYyRUK_bhNKj1Zty8Za8Y"

# Дефолтный список (тегается через @username — работает если они в чате)
DEFAULT_USERNAMES = [
    "limon1705",
    "wa6ingtonn",
    "areembee",
    "Tawer4K",
    "neskvikcpivom2",
]

# ─── Фильтр: только конкретная группа ───────────────────────────────────────

ALLOWED_CHAT_ID = -1003719823975

async def group_only(update: Update) -> bool:
    """Возвращает True только если сообщение из разрешённой группы."""
    return update.effective_chat.id == ALLOWED_CHAT_ID

# ─── Хранилище ───────────────────────────────────────────────────────────────

registered: dict[int, dict[int, str]] = {}   # chat_id -> {user_id: name}
sessions:   dict[int, dict] = {}              # chat_id -> сессия

# ─── Helpers ─────────────────────────────────────────────────────────────────

def get_registered(chat_id: int) -> dict[int, str]:
    return registered.setdefault(chat_id, {})

def default_mentions() -> str:
    return " ".join(f"@{u}" for u in DEFAULT_USERNAMES)

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

# ─── Команды ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update):
        return
    await update.message.reply_text(
        "🎮 <b>Dota 2 Bot</b>\n\n"
        "/dota — позвать всех прямо сейчас\n"
        "/schedule 21:00 — запланировать игру\n"
        "/reg — добавить себя в список\n"
        "/unreg — выйти из списка\n"
        "/players — список зарегистрированных\n"
        "/roulette — кто аутист?\n"
        "/cancel — отменить сессию",
        parse_mode="HTML",
    )

async def cmd_reg(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update):
        return
    user = update.effective_user
    chat_id = update.effective_chat.id
    pool = get_registered(chat_id)
    pool[user.id] = user.full_name or user.username or str(user.id)
    await update.message.reply_text(
        f'✅ <a href="tg://user?id={user.id}">{pool[user.id]}</a> добавлен в список!',
        parse_mode="HTML",
    )

async def cmd_unreg(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update):
        return
    user = update.effective_user
    pool = get_registered(update.effective_chat.id)
    if user.id in pool:
        name = pool.pop(user.id)
        await update.message.reply_text(f"👋 {name} удалён из списка.")
    else:
        await update.message.reply_text("Тебя нет в списке.")

async def cmd_players(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update):
        return
    chat_id = update.effective_chat.id
    pool = get_registered(chat_id)
    lines_def = "\n".join(f"{i+1}. @{u}" for i, u in enumerate(DEFAULT_USERNAMES))
    lines_reg = "\n".join(
        f'{i+1}. <a href="tg://user?id={uid}">{name}</a>'
        for i, (uid, name) in enumerate(pool.items())
    )
    text = f"📋 <b>Дефолтный список:</b>\n{lines_def}"
    if lines_reg:
        text += f"\n\n🎮 <b>Зарегистрированные (надёжный пинг):</b>\n{lines_reg}"
    await update.message.reply_text(text, parse_mode="HTML")

async def _start_session(update: Update, time_str: str | None):
    if not await group_only(update):
        return
    chat_id = update.effective_chat.id
    caller  = update.effective_user
    sessions[chat_id] = {
        "caller":    caller.full_name or caller.username or str(caller.id),
        "caller_id": caller.id,
        "yes": set(),
        "no":  set(),
        "time": time_str,
    }
    # Пинг-сообщение (отдельно, чтобы уведомления точно пришли)
    ping = registered_mentions(chat_id) or default_mentions()
    await update.message.reply_text(ping, parse_mode="HTML")
    # Карточка с кнопками
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


async def cmd_roulette(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update):
        return
    import random
    # Берём зарегистрированных, иначе дефолтный список
    pool = get_registered(update.effective_chat.id)
    if pool:
        uid, name = random.choice(list(pool.items()))
        victim = f'<a href="tg://user?id={uid}">{name}</a>'
    else:
        victim = "@" + random.choice(DEFAULT_USERNAMES)
    await update.message.reply_text(
        f"🎰 Рулетка крутится...\n\n🤡 <b>Аутист дня:</b> {victim}",
        parse_mode="HTML",
    )

async def cmd_cancel(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update):
        return
    chat_id = update.effective_chat.id
    if chat_id in sessions:
        sessions.pop(chat_id)
        await update.message.reply_text("🚫 Сессия отменена.")
    else:
        await update.message.reply_text("Нет активной сессии.")

# ─── Голосование ─────────────────────────────────────────────────────────────

async def on_vote(update: Update, _: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if update.effective_chat.type not in ("group", "supergroup"):
        return

    chat_id = update.effective_chat.id
    user    = update.effective_user
    session = sessions.get(chat_id)

    if not session:
        await query.answer("Сессия уже завершена.", show_alert=True)
        return

    # Авто-регистрация при голосовании
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

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("help",     cmd_start))
    app.add_handler(CommandHandler("reg",      cmd_reg))
    app.add_handler(CommandHandler("unreg",    cmd_unreg))
    app.add_handler(CommandHandler("players",  cmd_players))
    app.add_handler(CommandHandler("dota",     cmd_dota))
    app.add_handler(CommandHandler("schedule", cmd_schedule))
    app.add_handler(CommandHandler("roulette", cmd_roulette))
    app.add_handler(CommandHandler("cancel",   cmd_cancel))
    app.add_handler(CallbackQueryHandler(on_vote, pattern="^vote_"))
    logger.info("🎮 ErniFidBot запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
