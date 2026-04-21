import steam
import asyncio
from players_db import build_compat_dicts
from datetime import datetime, timezone, timedelta

TZ_MSK    = timezone(timedelta(hours=3))
TZ_ALMATY = timezone(timedelta(hours=5))


def _get_acct_to_discord_id() -> dict[int, int]:
    """Строит маппинг account_id -> discord_user_id из текущей базы."""
    _, _, DISCORD_TO_STEAM, DISCORD_USER_IDS = build_compat_dicts()
    result = {}
    for ds_username, steam_id in DISCORD_TO_STEAM.items():
        acct = int(steam_id) - 76561197960265728
        uid  = DISCORD_USER_IDS.get(ds_username)
        if uid:
            result[acct] = uid
    return result


def format_start_time(start_time: int) -> str:
    if not start_time:
        return ""
    dt_utc    = datetime.fromtimestamp(start_time, tz=timezone.utc)
    dt_almaty = dt_utc.astimezone(TZ_ALMATY)
    dt_msk    = dt_utc.astimezone(TZ_MSK)
    return f"📅 {dt_msk.strftime('%d.%m.%Y')} | {dt_msk.strftime('%H:%M')} МСК / {dt_almaty.strftime('%H:%M')} Алматы"


def get_rank(rank_tier) -> str:
    if not rank_tier:
        return "Uncalibrated"
    medals = {1:"Herald", 2:"Guardian", 3:"Crusader", 4:"Archon",
              5:"Legend", 6:"Ancient", 7:"Divine", 8:"Immortal"}
    tier = rank_tier // 10
    star = rank_tier % 10
    if tier == 8:
        return "Immortal"
    return f"{medals.get(tier, '?')} {star}⭐"


def get_position_fallback(p: dict) -> str:
    if p.get("is_roaming"):
        return "Роумер"
    mapping = {1: "Легкая", 2: "Мид", 3: "Сложная", 4: "Вне линии"}
    lane_role = p.get("lane_role")
    if lane_role in mapping:
        return mapping[lane_role]
    team_slot = p.get("team_slot", 0)
    positions = {0: "Pos 1", 1: "Pos 2", 2: "Pos 3", 3: "Pos 4", 4: "Pos 5"}
    return positions.get(team_slot, f"Pos {team_slot+1}")


def get_game_mode(game_mode: int, lobby_type: int) -> str:
    modes = {
        0: "Unknown", 1: "All Pick", 2: "Captain's Mode", 3: "Random Draft",
        4: "Single Draft", 5: "All Random", 7: "Diretide", 8: "Reverse CM",
        11: "All Draft", 12: "Least Played", 16: "Captains Draft",
        17: "Balanced Draft", 18: "Ability Draft", 20: "All Random Deathmatch",
        21: "1v1 Mid", 22: "All Pick Ranked", 23: "Turbo", 24: "Mutation",
    }
    return modes.get(game_mode, f"Mode {game_mode}")


def get_items(p: dict) -> str:
    slots = ["item_0", "item_1", "item_2", "item_3", "item_4", "item_5"]
    items = [steam.ITEM_NAMES.get(p.get(s, 0), "") for s in slots if p.get(s, 0)]
    return ", ".join(i for i in items if i) or "—"


SUPPORT_ITEMS = {
    "Glimmer Cape", "Force Staff", "Mekansm", "Pipe of Insight",
    "Lotus Orb", "Vladmir's Offering", "Arcane Boots", "Tranquil Boots",
    "Observer and Sentry Wards", "Ghost Scepter", "Eul's Scepter of Divinity",
    "Solar Crest", "Medallion of Courage", "Spirit Vessel"
}
CARRY_ITEMS = {
    "Battle Fury", "Manta Style", "Butterfly", "Mjollnir", "Daedalus",
    "Monkey King Bar", "Eye of Skadi", "Sange and Yasha", "Maelstrom",
    "Mask of Madness", "Helm of the Dominator"
}


def detect_position(p: dict, items_str: str) -> str:
    gpm = p.get("gold_per_min", 0)
    lh  = p.get("last_hits", 0)

    support_count = sum(1 for item in SUPPORT_ITEMS if item in items_str)
    carry_count   = sum(1 for item in CARRY_ITEMS   if item in items_str)

    if support_count >= 2 or (gpm < 380 and lh < 60):
        if gpm < 450:
            return "5 • Саппорт"
        return "4 • Роумер"

    if carry_count >= 1 or (lh > 250 and gpm > 600):
        return "1 • Керри"

    if gpm > 550 and lh > 150:
        return "2 • Мидер"
    if gpm > 450:
        return "3 • Оффлейнер"
    if gpm > 380:
        return "4 • Роумер"
    return "5 • Саппорт"


def format_match_message(match: dict, platform: str = "telegram") -> str:
    PLAYERS, _, _, _ = build_compat_dicts()
    acct_to_tg       = {int(v) - 76561197960265728: k for k, v in PLAYERS.items()}
    acct_to_discord  = _get_acct_to_discord_id()

    players_data = match.get("players", [])
    duration_min = match.get("duration", 0) // 60
    duration_sec = match.get("duration", 0) % 60
    radiant_win  = match.get("radiant_win", False)

    radiant = []
    dire    = []
    our_team_radiant = None
    our_players      = []

    for p in players_data:
        account_id = p.get("account_id", 0)
        slot       = p.get("player_slot", 0)
        is_radiant = slot < 128
        hero       = steam.HERO_NAMES.get(p.get("hero_id", 0), f"Hero#{p.get('hero_id',0)}")
        kills      = p.get("kills", 0)
        deaths     = p.get("deaths", 0)
        assists    = p.get("assists", 0)
        gpm        = p.get("gold_per_min", 0)
        xpm        = p.get("xp_per_min", 0)
        dmg        = p.get("hero_damage", 0)
        lh         = p.get("last_hits", 0)
        items_str  = get_items(p)

        tg_name = acct_to_tg.get(account_id) if account_id and account_id != 4294967295 else None

        if tg_name:
            if our_team_radiant is None:
                our_team_radiant = is_radiant
            rank = get_rank(p.get("rank_tier"))
            pos  = detect_position(p, get_items(p))

            if platform == "discord":
                discord_id = acct_to_discord.get(account_id)
                name_tag   = f"<@{discord_id}>" if discord_id else f"@{tg_name}"
                entry = (
                    f"  {name_tag} — **{hero}**\n"
                    f"    🏅 {rank} | {pos}\n"
                    f"    📊 {kills}/{deaths}/{assists} | GPM: {gpm} | XPM: {xpm}\n"
                    f"    ⚔️ Урон: {dmg:,} | LH: {lh}\n"
                    f"    🎒 {items_str}"
                )
            else:
                name_tag = f"@{tg_name}"
                entry = (
                    f"  {name_tag} — <b>{hero}</b>\n"
                    f"    🏅 {rank} | {pos}\n"
                    f"    📊 {kills}/{deaths}/{assists} | GPM: {gpm} | XPM: {xpm}\n"
                    f"    ⚔️ Урон: {dmg:,} | LH: {lh}\n"
                    f"    🎒 {items_str}"
                )
            our_players.append(name_tag)
        else:
            if platform == "discord":
                entry = (
                    f"  ? — **{hero}** ({kills}/{deaths}/{assists})\n    🎒 {items_str}"
                    if items_str != "—" else
                    f"  ? — **{hero}** ({kills}/{deaths}/{assists})"
                )
            else:
                entry = (
                    f"  ? — <b>{hero}</b> ({kills}/{deaths}/{assists})\n    🎒 {items_str}"
                    if items_str != "—" else
                    f"  ? — <b>{hero}</b> ({kills}/{deaths}/{assists})"
                )

        if is_radiant:
            radiant.append(entry)
        else:
            dire.append(entry)

    if our_team_radiant is None:
        our_team_radiant = True

    won           = (radiant_win and our_team_radiant) or (not radiant_win and not our_team_radiant)
    result_emoji  = "🏆 ПОБЕДА!" if won else "💀 ПОРАЖЕНИЕ"
    game_mode_str = get_game_mode(match.get("game_mode", 0), match.get("lobby_type", 0))
    time_str      = format_start_time(match.get("start_time", 0))

    lines = [
        result_emoji,
        f"⏱ Длительность: {duration_min}:{duration_sec:02d}",
        f"🎮 Матч #{match.get('match_id', '?')} | {game_mode_str}",
    ]
    if time_str:
        lines.append(time_str)
    lines += ["", "🟢 Radiant:"]
    lines.extend(radiant)
    lines += ["", "🔴 Dire:"]
    lines.extend(dire)
    if our_players:
        lines.append("")
        lines.append(f"🛡 Наши: {', '.join(our_players)}")

    return "\n".join(lines)
