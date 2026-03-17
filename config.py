TOKEN           = "8356191098:AAFu3axbr5OaEDlYyRUK_bhNKj1Zty8Za8Y"
STEAM_API_KEY   = "F25FE222BDDD5D2687073BAEF0D8CBB8"
ALLOWED_CHAT_ID = -1003719823975

PLAYERS = {
    "limon1705":      "76561199015459521",
    "wa6ingtonn":     "76561198312814207",
    "areembee":       "76561198385353313",
    "Tawer4K":        "76561198841600203",
    "neskvikcpivom2": "76561199004933239",
    "beekssus":       "76561198881056614",
}

HOST_TG  = "wa6ingtonn"
HOST_ID  = PLAYERS[HOST_TG]

DEFAULT_TAGS = list(PLAYERS.keys())

# Telegram username (lowercase) -> steam_id
TG_TO_STEAM = {tg.lower(): sid for tg, sid in PLAYERS.items()}

# Discord
DISCORD_TOKEN      = ""  # Установить в переменных окружения Railway
DISCORD_CHANNEL_ID = 680782297162973263

# Discord username (lowercase) -> steam_id
DISCORD_TO_STEAM = {
    "foryou4022":   PLAYERS["limon1705"],
    "wa6ington":    PLAYERS["wa6ingtonn"],
    "rbayka":       PLAYERS["areembee"],
    "tawer4k":      PLAYERS["Tawer4K"],
    ".alexandrov":  PLAYERS["neskvikcpivom2"],
    "beekssus":     PLAYERS["beekssus"],
}

# Discord username -> Discord User ID (для пингов <@ID>)
DISCORD_USER_IDS = {
    "foryou4022":   457572146345017366,
    "wa6ington":    428229894342967297,
    "rbayka":       153584815336062976,
    "tawer4k":      595244909020053526,
    ".alexandrov":  724191471795699754,
    "beekssus":     1129795182989148251,
}

# Gemini AI
GEMINI_API_KEY = ""  # Установить в переменных окружения Railway
