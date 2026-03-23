import logging
import asyncio
import aiohttp

from config import ALLOWED_CHAT_ID, HOST_ID, PLAYERS
from steam import fetch_hero_names, fetch_item_names, get_last_match_id, get_match_details, request_parse, count_our_players
import steam
from formatter import format_match_message
from ai_advisor import get_draft_advice, parse_draft

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

                # Умное ожидание — проверяем каждые 5/15/30 сек пока не появятся предметы
                match = None
                for delay in [5, 15, 30, 60]:
                    await asyncio.sleep(delay)
                    match = await get_match_details(session, mid)
                    if match:
                        has_items = any(
                            p.get("item_0") or p.get("item_1") or p.get("item_2")
                            for p in match.get("players", [])
                        )
                        if has_items:
                            break
                        match = None

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

                    # Анализ драфта через Gemini
                    try:
                        from steam import HERO_NAMES
                        our_heroes, enemy_heroes = parse_draft(match, set(PLAYERS.values()), HERO_NAMES)
                        if our_heroes and enemy_heroes:
                            await app.bot.send_message(
                                chat_id=ALLOWED_CHAT_ID,
                                text="⏳ Анализирую драфт...",
                                parse_mode="HTML"
                            )
                            advice = await get_draft_advice(our_heroes, enemy_heroes)
                            if advice:
                                await app.bot.send_message(
                                    chat_id=ALLOWED_CHAT_ID,
                                    text="🧠 <b>Анализ драфта:</b>\n\n" + advice,
                                    parse_mode="HTML"
                                )
                    except Exception as e:
                        logger.warning(f"Draft advice error: {e}")

            except Exception as e:
                logger.error(f"Monitor error: {e}")
                await asyncio.sleep(30)
