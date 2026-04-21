import os

# ─── Токены и ключи (из переменных окружения) ─────────────────────────────────
TOKEN           = os.environ.get("TELEGRAM_TOKEN",  "8356191098:AAFu3axbr5OaEDlYyRUK_bhNKj1Zty8Za8Y")
STEAM_API_KEY   = os.environ.get("STEAM_API_KEY",   "F25FE222BDDD5D2687073BAEF0D8CBB8")
ALLOWED_CHAT_ID = int(os.environ.get("TG_CHAT_ID",  "-1003719823975"))

# ─── Discord ──────────────────────────────────────────────────────────────────
DISCORD_TOKEN      = os.environ.get("DISCORD_TOKEN", "")
DISCORD_CHANNEL_ID = int(os.environ.get("DISCORD_CHANNEL_ID", "680782297162973263"))

# ─── Gemini AI ────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# ─── Динамические данные об игроках загружаются из players_db.py ──────────────
# Использование:
#   from players_db import build_compat_dicts
#   PLAYERS, TG_TO_STEAM, DISCORD_TO_STEAM, DISCORD_USER_IDS = build_compat_dicts()
#
# Для получения HOST (мониторинг матчей) — первый игрок в базе:
#   from players_db import get_all_players
#   host = get_all_players()[0] if get_all_players() else None

# ─── Telegram ID администраторов ─────────────────────────────────────────────
# Если пусто — все участники группы с правами администратора могут управлять
# Можно заполнить вручную: [123456789, 987654321]
TG_ADMIN_IDS: list[int] = []

# ─── Discord ID администраторов ──────────────────────────────────────────────
# Если пусто — пользователи с правами manage_guild могут управлять
DS_ADMIN_IDS: list[int] = []
