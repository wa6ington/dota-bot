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


async def get_player_position(hero: str, gpm: int, lh: int, items: str) -> str:
    """Определяет позицию игрока через Gemini по герою, GPM, LH и предметам."""
    import os
    api_key = os.environ.get("GEMINI_API_KEY", GEMINI_API_KEY)
    if not api_key:
        return "?"

    prompt = (
        f"Ты эксперт по Dota 2. Определи позицию игрока ТОЛЬКО по статистике, не по герою.\n"
        f"Герой: {hero}\n"
        f"GPM: {gpm} (керри >600, мид >550, оффлейн >450, саппорт <400)\n"
        f"Last Hits: {lh} (керри >200, мид >150, оффлейн >100, саппорт <80)\n"
        f"Предметы: {items}\n\n"
        f"Саппортовые предметы: Glimmer Cape, Force Staff, Mekansm, Wards, Pipe, Lotus Orb\n"
        f"Керри предметы: Battlefury, Manta, Butterfly, Mjollnir, Daedalus\n\n"
        f"Ответь ТОЛЬКО одним из этих вариантов без объяснений:\n"
        f"1 • Керри\n"
        f"2 • Мидер\n"
        f"3 • Оффлейнер\n"
        f"4 • Роумер\n"
        f"5 • Саппорт"
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 20, "temperature": 0.1}
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{GEMINI_URL}?key={api_key}",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                if r.status != 200:
                    return "?"
                data = await r.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                # Берём только первую строку и маппим на формат с числом
                raw = text.split("\n")[0].strip()
                mapping = {
                    "керри": "1 • Керри",
                    "мидер": "2 • Мидер",
                    "оффлейнер": "3 • Оффлейнер",
                    "роумер": "4 • Роумер",
                    "саппорт": "5 • Саппорт",
                    "легкая": "1 • Керри",
                    "мид": "2 • Мидер",
                    "сложная": "3 • Оффлейнер",
                    "вне линии": "4 • Роумер",
                }
                return mapping.get(raw.lower(), raw)
    except Exception as e:
        logger.warning(f"Position detection error: {e}")
        return "?"


async def get_match_analysis(players_data: list[dict]) -> str:
    """
    Полный AI разбор матча — net worth сравнение + идеальные шмотки.
    players_data — список наших игроков с данными.
    """
    import os
    api_key = os.environ.get("GEMINI_API_KEY", GEMINI_API_KEY)
    if not api_key:
        return ""

    duration_min = players_data[0].get("duration", 0) // 60 if players_data else 0

    players_text = ""
    for p in players_data:
        players_text += (
            f"- {p['name']} ({p['hero']}, {p['pos']}):\n"
            f"  K/D/A: {p['kills']}/{p['deaths']}/{p['assists']}\n"
            f"  GPM: {p['gpm']} | Net Worth: {p['net_worth']} gold\n"
            f"  Last Hits: {p['lh']}\n"
            f"  Предметы: {p['items']}\n\n"
        )

    prompt = (
        f"Ты профессиональный Dota 2 тренер. Разбери матч длительностью {duration_min} минут.\n\n"
        f"Наши игроки:\n{players_text}"
        f"Для каждого игрока дай на русском:\n"
        f"1. 💰 Net Worth: [реальный] (ожидалось ~[X] на {duration_min} мин для этой роли) — [оценка: норма/отставание/опережение]\n"
        f"2. ✅/❌ Сборка: что собрал правильно, чего не хватало\n"
        f"3. 🎒 Идеал: какие предметы надо было иметь к {duration_min} минуте\n\n"
        f"Будь конкретным, кратким, на русском. Используй эмодзи."
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 1000, "temperature": 0.7}
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{GEMINI_URL}?key={api_key}",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=20)
            ) as r:
                if r.status != 200:
                    logger.warning(f"Gemini API error: {r.status}")
                    return ""
                data = await r.json()
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        logger.warning(f"Match analysis error: {e}")
        return ""
