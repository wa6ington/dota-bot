#!/usr/bin/env python3
"""
🎮 Dota 2 Discord Bot
"""

import logging
import asyncio
import random
import aiohttp
import discord
import os
from discord.ext import commands, tasks
from discord import app_commands

from config import DISCORD_TO_STEAM, DISCORD_USER_IDS, HOST_ID, PLAYERS
from commands import format_two_timezones
from steam import (
    fetch_hero_names, fetch_item_names,
    get_last_match_id, get_match_details,
    request_parse, count_our_players
)
from formatter import format_match_message
from ai_advisor import get_draft_advice, parse_draft

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

DISCORD_TOKEN      = os.environ.get("DISCORD_TOKEN", "")
DISCORD_CHANNEL_ID = 680782297162973263
DISCORD_USERNAMES  = list(DISCORD_TO_STEAM.keys())

reported_matches: set[str] = set()
last_known_match: str | None = None

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


def discord_players_list() -> str:
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


# ─── Vote View ────────────────────────────────────────────────────────────────

class VoteView(discord.ui.View):
    def __init__(self, caller_name: str, time_str: str | None = None):
        super().__init__(timeout=None)
        self.caller_name = caller_name
        self.time_str    = time_str
        self.yes_ids:   set[int]  = set()
        self.no_ids:    set[int]  = set()
        self.yes_names: list[str] = []
        self.no_names:  list[str] = []

    def build_text(self) -> str:
        tags     = discord_players_list()
        time_str = f" в **{self.time_str}**" if self.time_str else ""
        return (
            f"⚔️ **{self.caller_name} зовёт в Dota 2{time_str}!**\n\n"
            f"👥 {tags}\n\n"
            f"✅ {len(self.yes_ids)}  —  {', '.join(self.yes_names) or '—'}\n"
            f"❌ {len(self.no_ids)}  —  {', '.join(self.no_names) or '—'}"
        )

    @discord.ui.button(label="✅ Иду!", style=discord.ButtonStyle.success, custom_id="vote_yes")
    async def vote_yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid, name = interaction.user.id, interaction.user.display_name
        if uid not in self.yes_ids:
            self.yes_ids.add(uid)
            self.yes_names.append(name)
        if uid in self.no_ids:
            self.no_ids.discard(uid)
            self.no_names = [n for n in self.no_names if n != name]
        await interaction.response.edit_message(content=self.build_text(), view=self)

    @discord.ui.button(label="❌ Не могу", style=discord.ButtonStyle.danger, custom_id="vote_no")
    async def vote_no(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid, name = interaction.user.id, interaction.user.display_name
        if uid not in self.no_ids:
            self.no_ids.add(uid)
            self.no_names.append(name)
        if uid in self.yes_ids:
            self.yes_ids.discard(uid)
            self.yes_names = [n for n in self.yes_names if n != name]
        await interaction.response.edit_message(content=self.build_text(), view=self)


# ─── события ─────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    logger.info(f"Discord bot ready: {bot.user}")
    monitor_loop.start()
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="/помощь"))
    try:
        for guild in bot.guilds:
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            logger.info(f"Synced {len(synced)} commands to {guild.name}")
    except Exception as e:
        logger.error(f"Sync error: {e}")


# ─── мониторинг ──────────────────────────────────────────────────────────────

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
            return

        logger.info(f"NEW match: {mid}")
        last_known_match = mid

        await request_parse(session, mid)
        await asyncio.sleep(60)

        match = await get_match_details(session, mid)
        if not match or count_our_players(match) < 2:
            return

        msg = format_match_message(match)
        if msg:
            reported_matches.add(mid)
            await channel.send(msg)

            # Анализ драфта через Gemini
            try:
                from steam import HERO_NAMES
                our_heroes, enemy_heroes = parse_draft(match, set(PLAYERS.values()), HERO_NAMES)
                if our_heroes and enemy_heroes:
                    advice = await get_draft_advice(our_heroes, enemy_heroes)
                    if advice:
                        await channel.send("🧠 **Анализ драфта:**\n\n" + advice)
            except Exception as e:
                logger.warning(f"Draft advice error: {e}")


# ─── slash-команды ────────────────────────────────────────────────────────────

@bot.tree.command(name="dota", description="⚔️ Позвать всех прямо сейчас")
async def slash_dota(interaction: discord.Interaction):
    view = VoteView(caller_name=interaction.user.display_name)
    await interaction.response.send_message(content=view.build_text(), view=view)

@bot.tree.command(name="schedule", description="📅 Запланировать игру")
@app_commands.describe(time="Например: 21:00 kz или 19:00 msk")
async def slash_schedule(interaction: discord.Interaction, time: str):
    formatted = format_two_timezones(time)
    if formatted is None:
        await interaction.response.send_message("❌ Неверный формат. Примеры: `21:00 kz` · `19:00 msk`", ephemeral=True)
        return
    view = VoteView(caller_name=interaction.user.display_name, time_str=formatted)
    await interaction.response.send_message(content=view.build_text(), view=view)

@bot.tree.command(name="lastmatch", description="🔍 Последний матч")
@app_commands.describe(user="Упомяни игрока или оставь пустым для себя")
async def slash_lastmatch(interaction: discord.Interaction, user: discord.Member = None):
    target   = user if user else interaction.user
    username = target.name.lower()
    steam_id = DISCORD_TO_STEAM.get(username)

    if not steam_id:
        await interaction.response.send_message(
            f"❌ `{target.display_name}` не в списке.\nСписок: {', '.join(f'`{u}`' for u in DISCORD_USERNAMES)}",
            ephemeral=True
        )
        return

    await interaction.response.send_message(f"🔍 Ищу последний матч **{target.display_name}**...")

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

        msg = format_match_message(match)
        if msg:
            await interaction.edit_original_response(content=msg)
        else:
            await interaction.edit_original_response(content="😕 Не удалось сформировать сообщение.")

@bot.tree.command(name="analyze", description="🔎 Анализ матча по ID")
@app_commands.describe(match_id="ID матча, например: 8726314725")
async def slash_analyze(interaction: discord.Interaction, match_id: str):
    if not match_id.isdigit():
        await interaction.response.send_message("❌ Неверный match_id.", ephemeral=True)
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

        msg = format_match_message(match)
        if msg:
            await interaction.edit_original_response(content=msg)
        else:
            await interaction.edit_original_response(content="😕 Не удалось сформировать сообщение.")

@bot.tree.command(name="draft", description="🧠 AI анализ драфта врагов")
@app_commands.describe(heroes="Герои врагов через пробел: invoker storm pudge")
async def slash_draft(interaction: discord.Interaction, heroes: str):
    enemy_heroes = [h.capitalize() for h in heroes.split()]
    await interaction.response.send_message(f"🧠 Анализирую драфт против: {', '.join(enemy_heroes)}...")
    advice = await get_draft_advice([], enemy_heroes)
    if advice:
        await interaction.edit_original_response(
            content="🧠 **Что собирать против " + ", ".join(enemy_heroes) + ":**\n\n" + advice
        )
    else:
        await interaction.edit_original_response(content="❌ Не удалось получить анализ.")

@bot.tree.command(name="roulette", description="🎰 Кто аутист дня?")
async def slash_roulette(interaction: discord.Interaction):
    uid = random.choice(list(DISCORD_USER_IDS.values()))
    await interaction.response.send_message(f"🎰 Рулетка крутится...\n\n🤡 **Аутист дня:** <@{uid}>")

@bot.tree.command(name="players", description="👥 Список игроков")
async def slash_players(interaction: discord.Interaction):
    lines = "\n".join(f"{i+1}. <@{uid}>" for i, uid in enumerate(DISCORD_USER_IDS.values()))
    await interaction.response.send_message(f"🎮 **Игроки:**\n{lines}")

@bot.tree.command(name="помощь", description="📋 Список команд")
async def slash_help(interaction: discord.Interaction):
    await interaction.response.send_message(
        "🎮 **Dota 2 Bot**\n\n"
        "`/dota` — Позвать всех прямо сейчас\n"
        "`/schedule 21:00 kz` — Запланировать игру\n"
        "`/lastmatch [игрок]` — Последний матч\n"
        "`/analyze ID` — Разбор матча по ID\n"
        "`/draft invoker storm` — AI анализ драфта\n"
        "`/roulette` — Кто аутист?\n"
        "`/players` — Список игроков",
        ephemeral=True
    )
