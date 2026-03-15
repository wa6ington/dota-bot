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
from discord import app_commands

import os
from config import DISCORD_TO_STEAM, DISCORD_USER_IDS, HOST_ID
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

DISCORD_USERNAMES = list(DISCORD_TO_STEAM.keys())

reported_matches: set[str] = set()
last_known_match: str | None = None

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


# ─── helpers ─────────────────────────────────────────────────────────────────

def discord_players_list() -> str:
    """Настоящие пинги всех игроков через <@user_id>."""
    return " ".join(f"<@{uid}>" for uid in DISCORD_USER_IDS.values())

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
    try:
        # Guild sync — команды появляются мгновенно (не ждём часами)
        for guild in bot.guilds:
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            logger.info(f"Synced {len(synced)} slash commands to guild: {guild.name}")
    except Exception as e:
        logger.error(f"Failed to sync slash commands: {e}")


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

        msg = format_match_message(match, platform="discord")
        if msg:
            reported_matches.add(mid)
            await channel.send(msg)
            logger.info(f"Discord: reported match {mid}")


# ─── slash-команды ────────────────────────────────────────────────────────────

@bot.tree.command(name="dota", description="⚔️ Позвать всех играть в Dota 2")
async def slash_dota(interaction: discord.Interaction):
    tags = discord_players_list()
    await interaction.response.send_message(
        f"⚔️ **{interaction.user.display_name} зовёт в Dota 2!**\n\n"
        f"👥 {tags}\n\n"
        f"Реагируйте: ✅ иду / ❌ не могу"
    )
    sent = await interaction.original_response()
    await sent.add_reaction("✅")
    await sent.add_reaction("❌")


@bot.tree.command(name="lastmatch", description="🔍 Показать твой последний матч в Dota 2")
async def slash_lastmatch(interaction: discord.Interaction):
    username = interaction.user.name.lower()
    steam_id = DISCORD_TO_STEAM.get(username)

    if not steam_id:
        players_list = ", ".join(f"`{u}`" for u in DISCORD_USERNAMES)
        await interaction.response.send_message(
            f"❌ `{interaction.user.display_name}` не в списке игроков.\n"
            f"Список: {players_list}",
            ephemeral=True
        )
        return

    await interaction.response.send_message(f"🔍 Ищу последний матч **{interaction.user.display_name}**...")

    async with aiohttp.ClientSession() as session:
        await fetch_hero_names(session)
        await fetch_item_names(session)
        mid = await get_last_match_id(session, steam_id)
        if not mid:
            await interaction.edit_original_response(content="❌ Не удалось найти матч.")
            return

        await request_parse(session, mid)

        async def update_status(text):
            await interaction.edit_original_response(content=text)

        match = await wait_for_match(session, mid, update_status)
        if not match:
            await interaction.edit_original_response(content="❌ Не удалось получить детали матча.")
            return

        result = format_match_message(match, platform="discord")
        if result:
            await interaction.edit_original_response(content=result)
        else:
            await interaction.edit_original_response(content="😕 Не удалось сформировать сообщение.")


@bot.tree.command(name="analyze", description="🔎 Анализ матча по ID")
@app_commands.describe(match_id="ID матча, например: 8726314725")
async def slash_analyze(interaction: discord.Interaction, match_id: str):
    if not match_id.isdigit():
        await interaction.response.send_message(
            "❌ Неверный match_id. Пример: `/analyze 8726314725`",
            ephemeral=True
        )
        return

    await interaction.response.send_message(f"🔍 Загружаю матч **#{match_id}**...")

    async with aiohttp.ClientSession() as session:
        await fetch_hero_names(session)
        await fetch_item_names(session)
        await request_parse(session, match_id)

        async def update_status(text):
            await interaction.edit_original_response(content=text)

        match = await wait_for_match(session, match_id, update_status)
        if not match:
            await interaction.edit_original_response(content="❌ Матч не найден. Попробуй позже.")
            return

        result = format_match_message(match, platform="discord")
        if result:
            await interaction.edit_original_response(content=result)
        else:
            await interaction.edit_original_response(content="😕 Не удалось сформировать сообщение.")


@bot.tree.command(name="roulette", description="🎰 Кто аутист дня?")
async def slash_roulette(interaction: discord.Interaction):
    uid = random.choice(list(DISCORD_USER_IDS.values()))
    await interaction.response.send_message(
        f"🎰 Рулетка крутится...\n\n🤡 **Аутист дня:** <@{uid}>"
    )


@bot.tree.command(name="players", description="👥 Список игроков")
async def slash_players(interaction: discord.Interaction):
    lines = "\n".join(f"{i+1}. <@{uid}>" for i, uid in enumerate(DISCORD_USER_IDS.values()))
    await interaction.response.send_message(f"🎮 **Игроки:**\n{lines}")


@bot.tree.command(name="помощь", description="📋 Список команд")
async def slash_help(interaction: discord.Interaction):
    await interaction.response.send_message(
        "🎮 **Dota 2 Bot**\n\n"
        "`/dota` — позвать всех играть\n"
        "`/lastmatch` — твой последний матч\n"
        "`/analyze` — анализ матча по ID\n"
        "`/roulette` — кто аутист дня?\n"
        "`/players` — список игроков\n",
        ephemeral=True
    )
