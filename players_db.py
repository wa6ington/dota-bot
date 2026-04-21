"""
📦 players_db.py — динамическая база данных игроков
Хранит данные в players_db.json, переживает перезапуски бота.

Структура записи:
{
  "tg_username":   "wa6ingtonn",       # Telegram @username (без @), может быть null
  "ds_username":   "wa6ington",        # Discord username (без @), может быть null
  "ds_user_id":    428229894342967297, # Discord user ID для пингов, может быть null
  "steam_id":      "76561198312814207" # SteamID64
}
"""

import json
import logging
import os
import aiohttp

logger = logging.getLogger(__name__)

DB_FILE = "players_db.json"   # путь к файлу относительно рабочей директории
STEAM_API_KEY = os.environ.get("STEAM_API_KEY", "")


# ─── внутренние функции ───────────────────────────────────────────────────────

def _load() -> list[dict]:
    """Загружает список игроков из JSON файла."""
    if not os.path.exists(DB_FILE):
        return []
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"DB load error: {e}")
    return []


def _save(players: list[dict]) -> bool:
    """Сохраняет список игроков в JSON файл."""
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(players, f, ensure_ascii=False, indent=2)
        return True
    except OSError as e:
        logger.error(f"DB save error: {e}")
        return False


# ─── публичные функции ────────────────────────────────────────────────────────

def get_all_players() -> list[dict]:
    """Возвращает всех игроков."""
    return _load()


def get_by_tg(username: str) -> dict | None:
    """Ищет игрока по Telegram username (без @, регистр не важен)."""
    username = username.lstrip("@").lower()
    for p in _load():
        if (p.get("tg_username") or "").lower() == username:
            return p
    return None


def get_by_ds(username: str) -> dict | None:
    """Ищет игрока по Discord username (без @, регистр не важен)."""
    username = username.lstrip("@").lower()
    for p in _load():
        if (p.get("ds_username") or "").lower() == username:
            return p
    return None


def get_by_steam(steam_id: str) -> dict | None:
    """Ищет игрока по SteamID64."""
    for p in _load():
        if p.get("steam_id") == steam_id:
            return p
    return None


def add_player(tg_username: str | None, ds_username: str | None,
               ds_user_id: int | None, steam_id: str) -> tuple[bool, str]:
    """
    Добавляет игрока. Возвращает (успех, сообщение).
    Проверяет дубликаты по steam_id, tg_username, ds_username.
    """
    players = _load()

    # Нормализация
    tg = tg_username.lstrip("@").lower() if tg_username else None
    ds = ds_username.lstrip("@").lower() if ds_username else None

    for p in players:
        if p.get("steam_id") == steam_id:
            return False, f"❌ SteamID `{steam_id}` уже зарегистрирован."
        if tg and (p.get("tg_username") or "").lower() == tg:
            return False, f"❌ TG-ник `@{tg}` уже зарегистрирован."
        if ds and (p.get("ds_username") or "").lower() == ds:
            return False, f"❌ DS-ник `@{ds}` уже зарегистрирован."

    entry = {
        "tg_username": tg,
        "ds_username": ds,
        "ds_user_id":  ds_user_id,
        "steam_id":    steam_id,
    }
    players.append(entry)
    if _save(players):
        tg_str = f"@{tg}" if tg else "—"
        ds_str = f"@{ds}" if ds else "—"
        return True, f"✅ Игрок добавлен!\nTG: {tg_str} | DS: {ds_str}\nSteam: `{steam_id}`"
    return False, "❌ Ошибка сохранения базы данных."


def remove_player(identifier: str) -> tuple[bool, str]:
    """
    Удаляет игрока по TG-нику, DS-нику или SteamID64.
    Возвращает (успех, сообщение).
    """
    players = _load()
    ident = identifier.lstrip("@").lower()

    new_list = []
    removed = None
    for p in players:
        tg = (p.get("tg_username") or "").lower()
        ds = (p.get("ds_username") or "").lower()
        sid = p.get("steam_id", "")
        if ident in (tg, ds, sid):
            removed = p
        else:
            new_list.append(p)

    if not removed:
        return False, f"❌ Игрок `{identifier}` не найден."

    if _save(new_list):
        tg_str = f"@{removed.get('tg_username')}" if removed.get("tg_username") else "—"
        ds_str = f"@{removed.get('ds_username')}" if removed.get("ds_username") else "—"
        return True, f"✅ Удалён: TG: {tg_str} | DS: {ds_str} | Steam: `{removed.get('steam_id')}`"
    return False, "❌ Ошибка сохранения."


def clear_all_players() -> tuple[bool, str]:
    """Очищает всю базу игроков."""
    if _save([]):
        return True, "✅ База игроков очищена."
    return False, "❌ Ошибка очистки базы."


def format_players_list(platform: str = "telegram") -> str:
    """Форматирует список игроков для вывода."""
    players = _load()
    if not players:
        return "👥 Список игроков пуст. Добавьте через /addplayer"

    lines = ["👥 **Игроки:**" if platform == "discord" else "👥 <b>Игроки:</b>"]
    for i, p in enumerate(players, 1):
        tg  = f"@{p['tg_username']}" if p.get("tg_username") else "—"
        ds  = f"@{p['ds_username']}" if p.get("ds_username") else "—"
        sid = p.get("steam_id", "?")
        short_sid = sid[-8:] if len(sid) > 8 else sid
        lines.append(f"{i}. TG:{tg} DS:{ds} Steam:...{short_sid}")
    return "\n".join(lines)


# ─── совместимость со старым кодом ───────────────────────────────────────────

def build_compat_dicts() -> tuple[dict, dict, dict, dict]:
    """
    Строит словари совместимые со старым кодом:
    PLAYERS, TG_TO_STEAM, DISCORD_TO_STEAM, DISCORD_USER_IDS
    """
    players = _load()
    PLAYERS          = {}  # tg_username -> steam_id
    TG_TO_STEAM      = {}  # tg_username.lower() -> steam_id
    DISCORD_TO_STEAM = {}  # ds_username.lower() -> steam_id
    DISCORD_USER_IDS = {}  # ds_username.lower() -> ds_user_id

    for p in players:
        sid = p.get("steam_id", "")
        tg  = p.get("tg_username")
        ds  = p.get("ds_username")
        did = p.get("ds_user_id")

        if tg and sid:
            PLAYERS[tg]     = sid
            TG_TO_STEAM[tg] = sid
        if ds and sid:
            DISCORD_TO_STEAM[ds] = sid
        if ds and did:
            DISCORD_USER_IDS[ds] = did

    return PLAYERS, TG_TO_STEAM, DISCORD_TO_STEAM, DISCORD_USER_IDS


# ─── Steam API хелперы ────────────────────────────────────────────────────────

async def resolve_steam_id(steam_input: str) -> tuple[str | None, str]:
    """
    Конвертирует любой ввод в SteamID64:
    - Уже SteamID64 (17 цифр) → возвращает как есть
    - steamcommunity.com/id/VANITY → резолвит через API
    - steamcommunity.com/profiles/STEAMID64 → извлекает
    - Просто vanity имя → резолвит через API
    Возвращает (steam_id64 | None, сообщение об ошибке)
    """
    raw = steam_input.strip().rstrip("/")

    # Уже SteamID64
    if raw.isdigit() and len(raw) == 17:
        return raw, ""

    # URL с profiles/
    if "/profiles/" in raw:
        parts = raw.split("/profiles/")
        candidate = parts[-1].split("/")[0]
        if candidate.isdigit() and len(candidate) == 17:
            return candidate, ""
        return None, "❌ Не удалось извлечь SteamID из ссылки на профиль."

    # vanity URL или /id/VANITY
    vanity = raw
    if "/id/" in raw:
        vanity = raw.split("/id/")[-1].split("/")[0]

    # Запрос к Steam API
    api_key = STEAM_API_KEY or os.environ.get("STEAM_API_KEY", "")
    if not api_key:
        return None, "❌ STEAM_API_KEY не задан."

    try:
        url = (
            f"https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/"
            f"?key={api_key}&vanityurl={vanity}"
        )
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json()
                resp = data.get("response", {})
                if resp.get("success") == 1:
                    return str(resp["steamid"]), ""
                return None, f"❌ Steam профиль `{vanity}` не найден."
    except Exception as e:
        return None, f"❌ Ошибка Steam API: {e}"
