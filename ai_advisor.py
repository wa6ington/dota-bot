"""
🧠 AI Draft Advisor — анализ драфта через Google Gemini
"""

import logging
import aiohttp

logger = logging.getLogger(__name__)

GEMINI_API_KEY = ""  # Устанавливается через env переменную
GEMINI_URL     = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"


async def get_draft_advice(our_heroes: list[str], enemy_heroes: list[str]) -> str:
    """
    Отправляет героев в Gemini и получает советы по айтемам.
    our_heroes   — список наших героев
    enemy_heroes — список героев врагов
    """
    import os
    api_key = os.environ.get("GEMINI_API_KEY", GEMINI_API_KEY)
    if not api_key:
        return ""

    our_str   = ", ".join(our_heroes) if our_heroes else "неизвестны"
    enemy_str = ", ".join(enemy_heroes) if enemy_heroes else "неизвестны"

    prompt = (
        f"Ты опытный Dota 2 тренер. Дай краткие советы на русском языке.\n\n"
        f"Наши герои: {our_str}\n"
        f"Герои врагов: {enemy_str}\n\n"
        f"Для каждого нашего героя напиши:\n"
        f"1. Какие 2-3 ключевых айтема собрать ПРОТИВ этого вражеского драфта\n"
        f"2. Одну главную угрозу от врагов которую надо учитывать\n\n"
        f"Будь конкретным и кратким. Формат:\n"
        f"🗡 [Герой]: [айтемы] — [угроза]"
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 500, "temperature": 0.7}
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{GEMINI_URL}?key={api_key}",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                if r.status != 200:
                    logger.warning(f"Gemini API error: {r.status}")
                    return ""
                data = await r.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                return text.strip()
    except Exception as e:
        logger.warning(f"Gemini request error: {e}")
        return ""


def parse_draft(match: dict, our_steam_ids: set, hero_names: dict) -> tuple[list, list]:
    """
    Разбирает picks_bans и players из матча.
    Возвращает (наши_герои, герои_врагов).
    """
    from config import PLAYERS

    acct_to_tg = {int(v) - 76561197960265728: k for k, v in PLAYERS.items()}
    players_data = match.get("players", [])

    # Определяем нашу команду по первому найденному игроку
    our_team_radiant = None
    our_heroes   = []
    enemy_heroes = []

    for p in players_data:
        account_id = p.get("account_id", 0)
        if account_id and account_id != 4294967295 and account_id in acct_to_tg:
            our_team_radiant = p.get("player_slot", 0) < 128
            break

    if our_team_radiant is None:
        our_team_radiant = True

    for p in players_data:
        slot       = p.get("player_slot", 0)
        is_radiant = slot < 128
        hero       = hero_names.get(p.get("hero_id", 0), f"Hero#{p.get('hero_id',0)}")

        if is_radiant == our_team_radiant:
            our_heroes.append(hero)
        else:
            enemy_heroes.append(hero)

    return our_heroes, enemy_heroes
