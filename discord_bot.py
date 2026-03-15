#!/usr/bin/env python3
"""
🎮 Dota 2 Discord Bot
"""

import logging
import asyncio
import random
import aiohttp
import discord
from discord.ext import commands, tasks

import os
from config import PLAYERS, DEFAULT_TAGS, TG_TO_STEAM, DISCORD_TO_STEAM, HOST_ID, STEAM_API_KEY
from steam import (
    fetch_hero_names, fetch_item_names,
    get_last_match_id, get_match_details,
    request_parse, count_our_players
)
from formatter import format_match_message

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

DISCORD_TOKEN      = os.environ.get("DISCORD_TOKEN", "")
DISCORD_CHANNEL_ID = 680782297162973263

reported_matches: set[str] = set()
last_known_match: str | None = None

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


# ─── helpers ─────────────────────────────────────────────────────────────────

def strip_html(text: str) -> str:
    """Убираем HTML теги для Discord — там используется markdown."""
    return (text
        .replace("<b>", "**").replace("</b>", "**")
        .replace("<i>", "*").replace("</i>", "*")
        .replace("<a href=\"tg://user?id=0\">", "").replace("</a>", "")
    )

async def wait_for_match(session, match_id: str, send_status) -> dict | None:
    delays = [5, 15, 30]
    for attempt, delay in enumerate(delays, start=1):
        await send_status(f"⏳ Ожидаю OpenDota... (попытка {attempt}/3)")
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


# ─── события ─────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    logger.info(f"Discord bot ready: {bot.user}")
    monitor_loop.start()
    await bot.tree.sync()


# ─── мониторинг матчей ────────────────────────────────────────────────────────

@tasks.loop(minutes=2)
async def monitor_loop():
    global last_known_match
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    if not channel:
        return

    async with aiohttp.ClientSession() as session:
        await fetch_hero_names(session)
        await fetch_item_names(session)

        mid = await get_last_match_id(session, HOST_ID)
        if not mid:
            return

        if last_known_match is None:
            last_known_match = mid
            logger.info(f"Discord monitor started. Last match: {mid}")
            return

        if mid == last_known_match or mid in reported_matches:
            logger.info(f"No new match (last={mid})")
            return

        logger.info(f"NEW match: {mid}")
        last_known_match = mid

        await request_parse(session, mid)
        await asyncio.sleep(60)

        match = await get_match_details(session, mid)
        if not match:
            return

        our_count = count_our_players(match)
        if our_count < 2:
            return

        msg = format_match_message(match)
        if msg:
            reported_matches.add(mid)
            await channel.send(strip_html(msg))
            logger.info(f"Discord: reported match {mid}")


# ─── команды ─────────────────────────────────────────────────────────────────

@bot.command(name="dota")
async def cmd_dota(ctx):
    """⚔️ Позвать всех играть"""
    tags = " ".join(f"@{u}" for u in DEFAULT_TAGS)
    await ctx.send(
        f"⚔️ **{ctx.author.display_name} зовёт в Dota 2!**\n\n"
        f"👥 {tags}\n\n"
        f"Реагируйте: ✅ иду / ❌ не могу"
    )
    msg = await ctx.channel.history(limit=1).flatten()
    if msg:
        await msg[0].add_reaction("✅")
        await msg[0].add_reaction("❌")

@bot.command(name="lastmatch")
async def cmd_lastmatch(ctx):
    """🔍 Последний матч того кто написал"""
    username = ctx.author.name.lower()
    steam_id = DISCORD_TO_STEAM.get(username)

    if not steam_id:
        players_list = ", ".join(f"@{u}" for u in PLAYERS)
        await ctx.send(
            f"❌ `{ctx.author.display_name}` не в списке игроков.\n"
            f"Список: {players_list}"
        )
        return

    status_msg = await ctx.send(f"🔍 Ищу последний матч **{username}**...")

    async with aiohttp.ClientSession() as session:
        await fetch_hero_names(session)
        await fetch_item_names(session)
        mid = await get_last_match_id(session, steam_id)
        if not mid:
            await status_msg.edit(content="❌ Не удалось найти матч.")
            return

        await request_parse(session, mid)

        async def update_status(text):
            await status_msg.edit(content=text)

        match = await wait_for_match(session, mid, update_status)
        if not match:
            await status_msg.edit(content="❌ Не удалось получить детали матча.")
            return

        msg = format_match_message(match)
        if msg:
            await status_msg.delete()
            await ctx.send(strip_html(msg))
        else:
            await status_msg.edit(content="😕 Не удалось сформировать сообщение.")

@bot.command(name="analyze")
async def cmd_analyze(ctx, match_id: str = None):
    """🔎 Анализ матча по ID"""
    if not match_id or not match_id.isdigit():
        await ctx.send("Использование: `!analyze 8726314725`")
        return

    status_msg = await ctx.send(f"🔍 Загружаю матч **#{match_id}**...")

    async with aiohttp.ClientSession() as session:
        await fetch_hero_names(session)
        await fetch_item_names(session)
        await request_parse(session, match_id)

        async def update_status(text):
            await status_msg.edit(content=text)

        match = await wait_for_match(session, match_id, update_status)
        if not match:
            await status_msg.edit(content="❌ Матч не найден. Попробуй позже.")
            return

        msg = format_match_message(match)
        if msg:
            await status_msg.delete()
            await ctx.send(strip_html(msg))
        else:
            await status_msg.edit(content="😕 Не удалось сформировать сообщение.")

@bot.command(name="roulette")
async def cmd_roulette(ctx):
    """🎰 Кто аутист дня?"""
    victim = random.choice(DEFAULT_TAGS)
    await ctx.send(f"🎰 Рулетка крутится...\n\n🤡 **Аутист дня:** @{victim}")

@bot.command(name="players")
async def cmd_players(ctx):
    """👥 Список игроков"""
    lines = "\n".join(f"{i+1}. @{u}" for i, u in enumerate(DEFAULT_TAGS))
    await ctx.send(f"🎮 **Игроки:**\n{lines}")

@bot.command(name="помощь")
async def cmd_help(ctx):
    """📋 Список команд"""
    await ctx.send(
        "🎮 **Dota 2 Bot**\n\n"
        "`!dota` — позвать всех играть\n"
        "`!lastmatch` — твой последний матч\n"
        "`!analyze 123456` — анализ матча по ID\n"
        "`!roulette` — кто аутист дня?\n"
        "`!players` — список игроков\n"
    )

