#!/usr/bin/env python3
"""
🎮 Dota 2 Bot — Telegram + Discord
"""

import logging
import asyncio
import threading

from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler

from config import TOKEN
from commands import (
    cmd_start, cmd_players, cmd_dota, cmd_schedule,
    cmd_cancel, cmd_roulette, cmd_lastmatch, cmd_analyze, on_vote
)
from monitor import monitor_matches

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


async def post_init(app):
    asyncio.create_task(monitor_matches(app))


def run_telegram():
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("help",      cmd_start))
    app.add_handler(CommandHandler("players",   cmd_players))
    app.add_handler(CommandHandler("dota",      cmd_dota))
    app.add_handler(CommandHandler("schedule",  cmd_schedule))
    app.add_handler(CommandHandler("cancel",    cmd_cancel))
    app.add_handler(CommandHandler("roulette",  cmd_roulette))
    app.add_handler(CommandHandler("lastmatch", cmd_lastmatch))
    app.add_handler(CommandHandler("analyze",   cmd_analyze))
    app.add_handler(CallbackQueryHandler(on_vote, pattern="^vote_"))
    logger.info("🎮 Telegram ErniFidBot запущен!")
    app.run_polling()


def run_discord():
    import os
    import discord
    from discord_bot import bot, DISCORD_TOKEN
    token = os.environ.get("DISCORD_TOKEN", DISCORD_TOKEN)
    if not token:
        logger.warning("DISCORD_TOKEN not set, skipping Discord bot")
        return
    try:
        bot.run(token)
    except Exception as e:
        logger.error(f"Discord bot error: {e}")


if __name__ == "__main__":
    t = threading.Thread(target=run_discord, daemon=True)
    t.start()
    logger.info("Discord bot thread started")
    run_telegram()
