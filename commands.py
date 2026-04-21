import logging
import asyncio
import random
import aiohttp

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import ALLOWED_CHAT_ID, TG_ADMIN_IDS
from players_db import (
    get_all_players, build_compat_dicts,
    add_player, remove_player, clear_all_players,
    format_players_list, resolve_steam_id, get_by_tg
)
from steam import fetch_hero_names, fetch_item_names, get_last_match_id, get_match_details, request_parse
from formatter import format_match_message

logger = logging.getLogger(__name__)

sessions: dict[int, dict] = {}


# ─── timezone helpers ─────────────────────────────────────────────────────────

def format_two_timezones(time_str: str) -> str | None:
    MSK_ALIASES = {"msk", "мск", "москва", "moscow"}
    KZ_ALIASES  = {"kz", "кз", "алматы", "almaty"}

    try:
        parts = time_str.strip().lower().split()
        if len(parts) < 2 or parts[-1] not in MSK_ALIASES | KZ_ALIASES:
            return None

        tz    = "msk" if parts[-1] in MSK_ALIASES else "kz"
        parts = parts[:-1]

        time_part = parts[0] if len(parts) == 1 else ":".join(parts[:2])
        hm = time_part.split(":")
        if len(hm) != 2:
            return None

        hours, minutes = int(hm[0]), int(hm[1])
        if not (0 <= hours <= 23 and 0 <= minutes <= 59):
            return None

        if tz == "msk":
            alm_hours = (hours + 2) % 24
            msk_hours = hours
        else:
            alm_hours = hours
            msk_hours = (hours - 2) % 24

        return f"{alm_hours:02d}:{minutes:02d} Алматы / {msk_hours:02d}:{minutes:02d} МСК"
    except (ValueError, IndexError):
        return None


# ─── helpers ──────────────────────────────────────────────────────────────────

async def group_only(update: Update) -> bool:
    return update.effective_chat.id == ALLOWED_CHAT_ID


async def is_tg_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Проверяет, является ли пользователь администратором группы."""
    user = update.effective_user
    if not user:
        return False
    # Явный список TG_ADMIN_IDS из конфига
    if TG_ADMIN_IDS and user.id in TG_ADMIN_IDS:
        return True
    # Иначе проверяем права в чате
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, user.id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


async def wait_for_match(session, match_id: str, send_status) -> dict | None:
    delays = [5, 15, 30]
    for attempt, delay in enumerate(delays, start=1):
        await send_status(f"⏳ Ожидаю ответа от OpenDota... (попытка {attempt}/3)")
        await asyncio.sleep(delay)
        match = await get_match_details(session, match_id)
        if not match:
            continue
        has_items = any(
            p.get("item_0") or p.get("item_1") or p.get("item_2")
            for p in match.get("players", [])
        )
        if has_items:
            return match
    return await get_match_details(session, match_id)


def all_mentions() -> str:
    PLAYERS, _, _, _ = build_compat_dicts()
    return " ".join(f"@{u}" for u in PLAYERS.keys())


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


# ─── базовые команды ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update):
        return
    await update.message.reply_text(
        "🎮 <b>Dota 2 Bot</b>\n\n"
        "<b>Игра:</b>\n"
        "/dota — Позвать всех прямо сейчас\n"
        "/schedule 21:00 KZ — Запланировать игру (указать пояс КЗ/МСК)\n"
        "/lastmatch [игрок] — Упомяни игрока или оставь пустым для себя\n"
        "/analyze ID — Разбор любого матча\n"
        "/draft invoker storm — AI анализ драфта\n"
        "/roulette — Кто аутист?\n"
        "/players — Список игроков\n"
        "/cancel — Отменить сессию\n\n"
        "<b>Управление игроками (только админы):</b>\n"
        "/addplayer @tg-ник @ds-ник steam/ссылка — Добавить игрока\n"
        "/removeplayer @ник или steamID — Удалить игрока\n"
        "/clearplayers — Очистить всю базу",
        parse_mode="HTML",
    )


async def cmd_players(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update):
        return
    await update.message.reply_text(format_players_list("telegram"), parse_mode="HTML")


# ─── управление игроками ──────────────────────────────────────────────────────

async def cmd_addplayer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /addplayer @tg-ник @ds-ник steamID_или_ссылка
    /addplayer @tg-ник - steamID_или_ссылка       (нет DS аккаунта)
    /addplayer - @ds-ник steamID_или_ссылка        (нет TG аккаунта)

    Steam можно передавать в любом виде:
      76561198312814207
      steamcommunity.com/id/wa6ingtonn
      steamcommunity.com/profiles/76561198312814207
      wa6ingtonn  (vanity имя)
    """
    if not await group_only(update):
        return
    if not await is_tg_admin(update, ctx):
        await update.message.reply_text("⛔ Только администраторы могут управлять игроками.")
        return

    args = ctx.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "❌ Использование:\n"
            "<code>/addplayer @tg_ник @ds_ник steamID_или_ссылка</code>\n"
            "<code>/addplayer @tg_ник - steamID</code>  (без DS)\n"
            "<code>/addplayer - @ds_ник steamID</code>  (без TG)\n\n"
            "Steam можно указывать как:\n"
            "• SteamID64: <code>76561198312814207</code>\n"
            "• Vanity-ник: <code>wa6ingtonn</code>\n"
            "• Ссылку: <code>steamcommunity.com/id/wa6ingtonn</code>",
            parse_mode="HTML"
        )
        return

    # Парсинг аргументов
    tg_arg  = args[0] if len(args) >= 1 else "-"
    ds_arg  = args[1] if len(args) >= 2 else "-"
    steam_arg = " ".join(args[2:]) if len(args) >= 3 else ""

    if not steam_arg:
        await update.message.reply_text("❌ Не указан Steam ID или ссылка на профиль.")
        return

    tg_username = None if tg_arg == "-" else tg_arg.lstrip("@")
    ds_username = None if ds_arg == "-" else ds_arg.lstrip("@")

    if not tg_username and not ds_username:
        await update.message.reply_text("❌ Укажи хотя бы один ник (TG или DS).")
        return

    # Резолвим Steam ID
    await update.message.reply_text("🔍 Проверяю Steam профиль...")
    steam_id, err = await resolve_steam_id(steam_arg)
    if not steam_id:
        await update.message.reply_text(err)
        return

    ok, msg = add_player(tg_username, ds_username, None, steam_id)
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_removeplayer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /removeplayer @tg-ник
    /removeplayer @ds-ник
    /removeplayer 76561198312814207
    """
    if not await group_only(update):
        return
    if not await is_tg_admin(update, ctx):
        await update.message.reply_text("⛔ Только администраторы могут управлять игроками.")
        return

    if not ctx.args:
        await update.message.reply_text(
            "❌ Использование: <code>/removeplayer @ник_или_steamID</code>",
            parse_mode="HTML"
        )
        return

    identifier = ctx.args[0]
    ok, msg = remove_player(identifier)
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_clearplayers(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Очищает всю базу игроков. Требует подтверждения."""
    if not await group_only(update):
        return
    if not await is_tg_admin(update, ctx):
        await update.message.reply_text("⛔ Только администраторы могут управлять игроками.")
        return

    # Требуем подтверждение
    confirm_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Да, очистить", callback_data="confirm_clear"),
        InlineKeyboardButton("❌ Отмена", callback_data="cancel_clear"),
    ]])
    await update.message.reply_text(
        "⚠️ <b>Вы уверены?</b> Это удалит всех игроков из базы данных.",
        parse_mode="HTML",
        reply_markup=confirm_kb
    )


async def on_clear_confirm(update: Update, _: ContextTypes.DEFAULT_TYPE):
    """Обработчик подтверждения очистки базы."""
    query = update.callback_query
    await query.answer()
    if query.data == "confirm_clear":
        ok, msg = clear_all_players()
        await query.edit_message_text(msg)
    else:
        await query.edit_message_text("❌ Отменено.")


# ─── сессии ───────────────────────────────────────────────────────────────────

async def _start_session(update: Update, time_str: str | None):
    if not await group_only(update):
        return
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
    raw = " ".join(ctx.args) if ctx.args else None
    if not raw:
        await update.message.reply_text("Использование: /schedule 21:00 kz  или  /schedule 19:00 msk")
        return
    time_str = format_two_timezones(raw)
    if time_str is None:
        await update.message.reply_text(
            "❌ Неверный формат.\nПримеры: /schedule 21:00 kz · /schedule 19:00 msk"
        )
        return
    await _start_session(update, time_str)


async def cmd_cancel(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update):
        return
    chat_id = update.effective_chat.id
    if chat_id in sessions:
        sessions.pop(chat_id)
        await update.message.reply_text("🚫 Сессия отменена.")
    else:
        await update.message.reply_text("Нет активной сессии.")


async def cmd_roulette(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update):
        return
    PLAYERS, _, _, _ = build_compat_dicts()
    tags = list(PLAYERS.keys())
    if not tags:
        await update.message.reply_text("👥 Нет игроков в базе!")
        return
    victim = "@" + random.choice(tags)
    await update.message.reply_text(
        f"🎰 Рулетка крутится...\n\n🤡 <b>Аутист дня:</b> {victim}",
        parse_mode="HTML",
    )


# ─── матчи ────────────────────────────────────────────────────────────────────

async def cmd_lastmatch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update):
        return

    PLAYERS, TG_TO_STEAM, _, _ = build_compat_dicts()

    if ctx.args:
        target_name = ctx.args[0].lstrip("@").lower()
    else:
        user = update.effective_user
        target_name = (user.username or "").lower()

    steam_id = TG_TO_STEAM.get(target_name)
    if not steam_id:
        await update.message.reply_text(
            f"❌ @{target_name} не в списке игроков.\n"
            f"Список: {', '.join('@'+u for u in PLAYERS)}"
        )
        return

    await update.message.reply_text(f"🔍 Ищу последний матч @{target_name}...")
    async with aiohttp.ClientSession() as session:
        await fetch_hero_names(session)
        await fetch_item_names(session)
        mid = await get_last_match_id(session, steam_id)
        if not mid:
            await update.message.reply_text("❌ Не удалось найти матч.")
            return
        await request_parse(session, mid)
        match = await wait_for_match(session, mid, update.message.reply_text)
        if not match:
            await update.message.reply_text("❌ Не удалось получить детали матча.")
            return
        msg = format_match_message(match)
        if msg:
            await update.message.reply_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_text("😕 Не удалось сформировать сообщение.")


async def cmd_analyze(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update):
        return
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
        match = await wait_for_match(session, match_id, update.message.reply_text)
        if not match:
            await update.message.reply_text("❌ Матч не найден. Попробуй позже.")
            return
        msg = format_match_message(match)
        if msg:
            await update.message.reply_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_text("😕 Не удалось сформировать сообщение.")


async def cmd_draft(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await group_only(update):
        return
    if not ctx.args:
        await update.message.reply_text(
            "Использование: /draft invoker storm pudge\nВведи героев врагов через пробел"
        )
        return
    enemy_heroes = [h.capitalize() for h in ctx.args]
    await update.message.reply_text(f"🧠 Анализирую драфт против: {', '.join(enemy_heroes)}...")
    from ai_advisor import get_draft_advice
    advice = await get_draft_advice([], enemy_heroes)
    if advice:
        await update.message.reply_text(
            "🧠 <b>Что собирать против " + ", ".join(enemy_heroes) + ":</b>\n\n" + advice,
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text("❌ Не удалось получить анализ. Попробуй позже.")


# ─── callback handlers ────────────────────────────────────────────────────────

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
