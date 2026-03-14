import logging
import aiohttp
from config import STEAM_API_KEY, PLAYERS

logger = logging.getLogger(__name__)

HERO_NAMES: dict[int, str] = {}
ITEM_NAMES: dict[int, str] = {}


async def fetch_hero_names(session: aiohttp.ClientSession):
    global HERO_NAMES
    if HERO_NAMES:
        return
    try:
        async with session.get("https://api.opendota.com/api/heroes", timeout=aiohttp.ClientTimeout(total=10)) as r:
            heroes = await r.json()
            HERO_NAMES = {h["id"]: h["localized_name"] for h in heroes}
            logger.info(f"Loaded {len(HERO_NAMES)} heroes")
    except Exception as e:
        logger.warning(f"Could not load hero names: {e}")


async def fetch_item_names(session: aiohttp.ClientSession):
    global ITEM_NAMES
    if ITEM_NAMES:
        return
    try:
        async with session.get("https://api.opendota.com/api/constants/items", timeout=aiohttp.ClientTimeout(total=10)) as r:
            data = await r.json()
            ITEM_NAMES = {v["id"]: v["dname"] for k, v in data.items() if "id" in v and "dname" in v}
            logger.info(f"Loaded {len(ITEM_NAMES)} items")
    except Exception as e:
        logger.warning(f"Could not load item names: {e}")


async def get_last_match_id(session: aiohttp.ClientSession, steam_id: str) -> str | None:
    try:
        account_id = int(steam_id) - 76561197960265728
        url = (
            f"https://api.steampowered.com/IDOTA2Match_570/GetMatchHistory/v1/"
            f"?key={STEAM_API_KEY}&account_id={account_id}&matches_requested=1"
        )
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            data = await r.json()
            matches = data.get("result", {}).get("matches", [])
            if matches:
                return str(matches[0]["match_id"])
    except Exception as e:
        logger.warning(f"get_last_match_id error: {e}")
    return None


async def get_match_details(session: aiohttp.ClientSession, match_id: str) -> dict | None:
    # OpenDota первым — там есть предметы и статы
    try:
        async with session.get(f"https://api.opendota.com/api/matches/{match_id}", timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status == 200:
                data = await r.json()
                if data.get("match_id") or data.get("players"):
                    logger.info(f"Got match {match_id} from OpenDota")
                    return data
    except Exception as e:
        logger.warning(f"OpenDota match details error: {e}")
    # Steam API fallback
    try:
        url = f"https://api.steampowered.com/IDOTA2Match_570/GetMatchDetails/v1/?key={STEAM_API_KEY}&match_id={match_id}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
            data = await r.json()
            result = data.get("result", {})
            if result.get("match_id"):
                logger.info(f"Got match {match_id} from Steam API")
                return result
    except Exception as e:
        logger.warning(f"Steam match details error: {e}")
    return None


async def request_parse(session: aiohttp.ClientSession, match_id: str):
    try:
        async with session.post(f"https://api.opendota.com/api/request/{match_id}", timeout=aiohttp.ClientTimeout(total=10)) as r:
            logger.info(f"Requested parse for {match_id}: {r.status}")
    except Exception as e:
        logger.warning(f"Parse request error: {e}")


def count_our_players(match: dict) -> int:
    acct_to_tg = {int(v) - 76561197960265728: k for k, v in PLAYERS.items()}
    count = 0
    for p in match.get("players", []):
        account_id = p.get("account_id", 0)
        if account_id and account_id != 4294967295 and account_id in acct_to_tg:
            count += 1
    return count
