from config import PLAYERS
from steam import HERO_NAMES, ITEM_NAMES


def get_rank(rank_tier) -> str:
    if not rank_tier:
        return "Uncalibrated"
    medals = {1:"Herald", 2:"Guardian", 3:"Crusader", 4:"Archon",
              5:"Legend", 6:"Ancient", 7:"Divine", 8:"Immortal"}
    tier = rank_tier // 10
    star = rank_tier % 10
    name = medals.get(tier, "?")
    if tier == 8:
        return "Immortal"
    return f"{name} {star}⭐"


def get_position(team_slot: int) -> str:
    positions = {
        0: "Pos 1 (Carry)",
        1: "Pos 2 (Mid)",
        2: "Pos 3 (Offlane)",
        3: "Pos 4 (Soft Support)",
        4: "Pos 5 (Hard Support)",
    }
    return positions.get(team_slot, f"Pos {team_slot+1}")


def get_game_mode(game_mode: int, lobby_type: int) -> str:
    modes = {
        0: "Unknown", 1: "All Pick", 2: "Captain's Mode", 3: "Random Draft",
        4: "Single Draft", 5: "All Random", 7: "Diretide", 8: "Reverse CM",
        11: "All Draft", 12: "Least Played", 16: "Captains Draft",
        17: "Balanced Draft", 18: "Ability Draft", 20: "All Random Deathmatch",
        21: "1v1 Solo Mid", 22: "All Pick Ranked", 23: "Turbo", 24: "Mutation",
    }
    lobbies = {0: "Normal", 1: "Practice", 2: "Tournament",
               5: "Team Match", 6: "Solo Queue", 7: "Ranked", 9: "1v1 Mid"}
    mode   = modes.get(game_mode, f"Mode {game_mode}")
    lobby  = lobbies.get(lobby_type, "")
    if lobby and lobby != "Normal":
        return f"{mode} ({lobby})"
    return mode


def get_items(p: dict) -> str:
    slots = ["item_0", "item_1", "item_2", "item_3", "item_4", "item_5"]
    items = [ITEM_NAMES.get(p.get(s, 0), "") for s in slots if p.get(s, 0)]
    return ", ".join(i for i in items if i) or "—"


def format_match_message(match: dict) -> str:
    players_data = match.get("players", [])
    duration_min = match.get("duration", 0) // 60
    duration_sec = match.get("duration", 0) % 60
    radiant_win  = match.get("radiant_win", False)
    acct_to_tg   = {int(v) - 76561197960265728: k for k, v in PLAYERS.items()}

    radiant = []
    dire    = []
    our_team_radiant = None
    our_players      = []

    for p in players_data:
        account_id = p.get("account_id", 0)
        slot       = p.get("player_slot", 0)
        is_radiant = slot < 128
        hero       = HERO_NAMES.get(p.get("hero_id", 0), f"Hero#{p.get('hero_id',0)}")
        kills      = p.get("kills", 0)
        deaths     = p.get("deaths", 0)
        assists    = p.get("assists", 0)
        gpm        = p.get("gold_per_min", 0)
        xpm        = p.get("xp_per_min", 0)
        dmg        = p.get("hero_damage", 0)
        lh         = p.get("last_hits", 0)
        team_slot  = p.get("team_slot", 0)
        items_str  = get_items(p)

        tg_name = acct_to_tg.get(account_id) if account_id and account_id != 4294967295 else None

        if tg_name:
            our_players.append(tg_name)
            if our_team_radiant is None:
                our_team_radiant = is_radiant
            rank  = get_rank(p.get("rank_tier"))
            pos   = get_position(team_slot)
            entry = (
                f"  @{tg_name} — <b>{hero}</b>\n"
                f"    🏅 {rank} | {pos}\n"
                f"    📊 {kills}/{deaths}/{assists} | GPM: {gpm} | XPM: {xpm}\n"
                f"    ⚔️ Урон: {dmg:,} | LH: {lh}\n"
                f"    🎒 {items_str}"
            )
        else:
            entry = f"  ? — <b>{hero}</b> ({kills}/{deaths}/{assists})"

        if is_radiant:
            radiant.append(entry)
        else:
            dire.append(entry)

    if our_team_radiant is None:
        our_team_radiant = True

    won           = (radiant_win and our_team_radiant) or (not radiant_win and not our_team_radiant)
    result_emoji  = "🏆 ПОБЕДА!" if won else "💀 ПОРАЖЕНИЕ"
    game_mode_str = get_game_mode(match.get("game_mode", 0), match.get("lobby_type", 0))

    lines = [
        result_emoji,
        f"⏱ Длительность: {duration_min}:{duration_sec:02d}",
        f"🎮 Матч #{match.get('match_id', '?')} | {game_mode_str}",
        "",
        "🟢 Radiant:",
    ]
    lines.extend(radiant)
    lines.append("")
    lines.append("🔴 Dire:")
    lines.extend(dire)

    if our_players:
        lines.append("")
        lines.append(f"🛡 Наши: {', '.join('@'+p for p in our_players)}")

    return "\n".join(lines)
