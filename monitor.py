import logging
import asyncio
import aiohttp
import steam

from config import ALLOWED_CHAT_ID, HOST_ID, PLAYERS
from steam import fetch_hero_names, fetch_item_names, get_last_match_id, get_match_details, request_parse, count_our_players
from formatter import format_match_message, detect_position
from ai_advisor import get_match_analysis

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

                # Умное ожидание
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

                # Отправляем результат матча
                msg = format_match_message(match)
                if msg:
                    reported_matches.add(mid)
                    await app.bot.send_message(chat_id=ALLOWED_CHAT_ID, text=msg, parse_mode="HTML")
                    logger.info(f"Reported match {mid}")

                # AI полный разбор матча
                try:
                    acct_to_tg = {int(v) - 76561197960265728: k for k, v in PLAYERS.items()}
                    our_players_data = []

                    for p in match.get("players", []):
                        account_id = p.get("account_id", 0)
                        tg_name = acct_to_tg.get(account_id)
                        if not tg_name or account_id == 4294967295:
                            continue
                        hero = steam.HERO_NAMES.get(p.get("hero_id", 0), f"Hero#{p.get('hero_id',0)}")
                        items_str = ", ".join(
                            steam.ITEM_NAMES.get(p.get(s, 0), "")
                            for s in ["item_0","item_1","item_2","item_3","item_4","item_5"]
                            if p.get(s, 0)
                        )
                        items_str = ", ".join(i for i in items_str.split(", ") if i)
                        pos = detect_position(p, items_str)
                        our_players_data.append({
                            "name":      f"@{tg_name}",
                            "hero":      hero,
                            "pos":       pos,
                            "kills":     p.get("kills", 0),
                            "deaths":    p.get("deaths", 0),
                            "assists":   p.get("assists", 0),
                            "gpm":       p.get("gold_per_min", 0),
                            "net_worth": p.get("net_worth", 0),
                            "lh":        p.get("last_hits", 0),
                            "items":     items_str or "—",
                            "duration":  match.get("duration", 0),
                        })

                    if our_players_data:
                        logger.info("Requesting AI match analysis...")
                        analysis = await get_match_analysis(our_players_data)
                        if analysis:
                            await app.bot.send_message(
                                chat_id=ALLOWED_CHAT_ID,
                                text="🧠 <b>Разбор матча:</b>\n\n" + analysis,
                                parse_mode="HTML"
                            )
                            logger.info("AI analysis sent")
                        else:
                            logger.warning("AI analysis returned empty")
                except Exception as e:
                    logger.error(f"Match analysis error: {e}")

            except Exception as e:
                logger.error(f"Monitor error: {e}")
                await asyncio.sleep(30)
