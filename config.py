TOKEN           = "8356191098:AAFu3axbr5OaEDlYyRUK_bhNKj1Zty8Za8Y"
STEAM_API_KEY   = "F25FE222BDDD5D2687073BAEF0D8CBB8"
ALLOWED_CHAT_ID = -1003719823975

PLAYERS = {
    "limon1705":      "76561199015459521",
    "wa6ingtonn":     "76561198312814207",
    "areembee":       "76561198385353313",
    "Tawer4K":        "76561198841600203",
    "neskvikcpivom2": "76561199004933239",
}

HOST_TG  = "wa6ingtonn"
HOST_ID  = PLAYERS[HOST_TG]

DEFAULT_TAGS = list(PLAYERS.keys())

# Telegram username (lowercase) -> steam_id
TG_TO_STEAM = {tg.lower(): sid for tg, sid in PLAYERS.items()}
