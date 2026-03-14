import logging
import asyncio
import aiohttp

from config import ALLOWED_CHAT_ID, HOST_ID
from steam import fetch_hero_names, fetch_item_names, get_last_match_id, get_match_details, request_parse, count_our_players
from formatter import format_match_message

logger = logging.getLogger(__name__)

reported_matches: set[str] = set()
last_known_match: str | None = None


async def monitor_matches(app):
    global last_known_match
    await asyncio.sleep(10)

    async with aiohttp.ClientSession() as session:
        await fetch_hero_names(session)
        await fetch_item_names(session)

        last_known_match = await get_last_match_id(session, HOST_ID)
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

                await request_parse(session, mid)
                await asyncio.sleep(60)

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
