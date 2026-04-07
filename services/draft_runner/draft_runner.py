#!/usr/bin/env python3
"""
Draft runner for cubesim.

Player 1 is human. Players 2-4 are AI (random strategy).

Pack 1 (15 cards): 1 pick per pass, rotate left.
Packs 2-4 (20 cards): 2 picks per pass, alternate direction (even packs pass right).

Logs: draft-<id>/logs/pack_N_log.json
Final picks: draft-<id>/drafted/player_N.json

Usage:
    python draft_runner.py                          # uses latest draft
    python draft_runner.py draft-20260406-...-uuid  # specific draft
"""

import json
import os
import random
import sys
from pathlib import Path

DRAFTS_DIR   = Path(os.getenv("DRAFTS_DIR", "/drafts"))
N_PLAYERS    = 4
HUMAN        = 0  # 0-indexed
PICKS_PACK   = {1: 1, 2: 2, 3: 2, 4: 2}
# direction: +1 = left (player i passes to i+1), -1 = right (i passes to i-1)
DIRECTION    = {1: +1, 2: -1, 3: +1, 4: -1}


# ─────────────────────────────────────────────────────────────
# I/O helpers
# ─────────────────────────────────────────────────────────────

# Column widths (characters)
_W_NAME    = 28
_W_MANA    = 14
_W_TYPE    = 26
_W_ORACLE  = 42
_W_PT      = 5

_HEADER = (
    f"  {'':4} "
    f"| {'Name':{_W_NAME}} "
    f"| {'Cost':{_W_MANA}} "
    f"| {'Type':{_W_TYPE}} "
    f"| {'Oracle Text':{_W_ORACLE}} "
    f"| {'P/T':{_W_PT}} |"
)
_DIVIDER = "  " + "-" * (len(_HEADER) - 2)


def _trunc(text: str | None, width: int) -> str:
    text = (text or "").replace("\n", " ")
    return text if len(text) <= width else text[: width - 1] + "…"


def card_line(card: dict, idx: int | None = None) -> str:
    prefix = f"{idx:3}." if idx is not None else "    "
    name   = _trunc(card.get("name"), _W_NAME)
    mana   = _trunc(card.get("mana_cost"), _W_MANA)
    tline  = _trunc(card.get("type_line"), _W_TYPE)
    oracle = _trunc(card.get("oracle_text"), _W_ORACLE)
    power  = card.get("power")
    tough  = card.get("toughness")
    pt     = _trunc(f"{power}/{tough}" if power is not None else "", _W_PT)
    return (
        f"  {prefix} "
        f"| {name:{_W_NAME}} "
        f"| {mana:{_W_MANA}} "
        f"| {tline:{_W_TYPE}} "
        f"| {oracle:{_W_ORACLE}} "
        f"| {pt:{_W_PT}} |"
    )


def print_pack(cards: list[dict]) -> None:
    print(_HEADER)
    print(_DIVIDER)
    for i, card in enumerate(cards, 1):
        print(card_line(card, i))


def show_drafted(cards: list[dict], label: str = "Your drafted cards") -> None:
    print(f"\n  {label} ({len(cards)} total):")
    print(_HEADER)
    print(_DIVIDER)
    for card in cards:
        print(card_line(card))


def human_pick(pack: list[dict], n_picks: int, pass_num: int,
               drafted: list[dict]) -> list[dict]:
    """Present the pack to the human and collect n_picks selections."""
    selected    = []
    working     = list(pack)

    for pick_num in range(1, n_picks + 1):
        width = len(_HEADER)
        print(f"\n{'═' * width}")
        print(f"  Pass {pass_num}  |  Pick {pick_num} of {n_picks}  |  {len(working)} cards in pack")
        print(f"{'═' * width}")
        print(f"  You have drafted {len(drafted)} card(s) total.  "
              f"Type 'l' to list them.\n")

        print_pack(working)

        while True:
            try:
                raw = input(f"\n  Pick (1–{len(working)}) or 'l' to list your picks: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nDraft interrupted.")
                sys.exit(0)

            if raw.lower() == "l":
                show_drafted(drafted)
                continue

            try:
                idx = int(raw) - 1
            except ValueError:
                print("  Enter a number or 'l'.")
                continue

            if not (0 <= idx < len(working)):
                print(f"  Enter a number between 1 and {len(working)}.")
                continue

            card = working.pop(idx)
            selected.append(card)
            drafted.append(card)
            print(f"\n  ✓ You picked: {card['name']}")
            break

    return selected


def ai_pick(pack: list[dict], n_picks: int, player_num: int) -> list[dict]:
    """Pick the n highest-ranked cards by EDHREC rank (lower rank = more popular)."""
    sorted_pack = sorted(pack, key=lambda c: c.get("edhrec_rank") or 999999)
    return sorted_pack[:min(n_picks, len(sorted_pack))]


# ─────────────────────────────────────────────────────────────
# Core draft logic
# ─────────────────────────────────────────────────────────────

def run_pack(pack_num: int, initial_packs: list[list[dict]],
             drafted: list[list[dict]], logs_dir: Path) -> None:
    n_picks   = PICKS_PACK[pack_num]
    direction = DIRECTION[pack_num]
    dir_label = "→ left" if direction == +1 else "← right"

    print(f"\n{'█'*58}")
    print(f"  PACK {pack_num}  ·  {len(initial_packs[0])} cards  ·  "
          f"{n_picks} pick(s)/pass  ·  passing {dir_label}")
    print(f"{'█'*58}")

    packs      = [list(p) for p in initial_packs]
    log_passes = []
    pass_num   = 0

    while any(packs):
        pass_num += 1
        pass_entry = {"pass": pass_num, "selections": []}

        for player_idx in range(N_PLAYERS):
            if not packs[player_idx]:
                continue

            n = min(n_picks, len(packs[player_idx]))

            if player_idx == HUMAN:
                picks = human_pick(packs[player_idx], n, pass_num, drafted[HUMAN])
            else:
                picks = ai_pick(packs[player_idx], n, player_idx + 1)

            for card in picks:
                packs[player_idx].remove(card)
                if player_idx != HUMAN:          # human already appended in human_pick
                    drafted[player_idx].append(card)
                pass_entry["selections"].append({
                    "player": player_idx + 1,
                    "card":   card,
                })

        log_passes.append(pass_entry)

        # Rotate packs
        # direction +1 (pass left): pack held by player i goes to player i+1,
        #   so player i now holds what player i-1 had.
        packs = [packs[(i - direction) % N_PLAYERS] for i in range(N_PLAYERS)]

    log_path = logs_dir / f"pack_{pack_num}_log.json"
    log_path.write_text(json.dumps({
        "pack":          pack_num,
        "picks_per_pass": n_picks,
        "direction":     "left" if direction == +1 else "right",
        "passes":        log_passes,
    }, indent=2))
    print(f"\n  Pack {pack_num} complete — log saved to logs/pack_{pack_num}_log.json")


# ─────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────

def find_latest_draft(drafts_dir: Path) -> Path:
    dirs = sorted(
        (d for d in drafts_dir.iterdir() if d.is_dir() and d.name.startswith("draft-")),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    if not dirs:
        raise RuntimeError(f"No draft directories found in {drafts_dir}")
    return dirs[0]


def load_sealed(draft_dir: Path) -> list[dict]:
    players = []
    for i in range(1, N_PLAYERS + 1):
        path = draft_dir / "sealed" / f"player_{i}.json"
        if not path.exists():
            raise RuntimeError(f"Sealed pool not found: {path}")
        players.append(json.loads(path.read_text()))
    return players


def main() -> None:
    if len(sys.argv) > 1:
        name = sys.argv[1]
        draft_dir = Path(name) if Path(name).is_absolute() else DRAFTS_DIR / name
    else:
        draft_dir = find_latest_draft(DRAFTS_DIR)

    if not draft_dir.exists():
        print(f"Error: {draft_dir} does not exist", file=sys.stderr)
        sys.exit(1)

    print(f"\n  Draft: {draft_dir.name}")

    sealed_players = load_sealed(draft_dir)

    logs_dir    = draft_dir / "logs"
    drafted_dir = draft_dir / "drafted"
    logs_dir.mkdir(exist_ok=True)
    drafted_dir.mkdir(exist_ok=True)

    # drafted[i] accumulates every card player i selects across all packs
    drafted: list[list[dict]] = [[] for _ in range(N_PLAYERS)]

    for pack_num in range(1, 5):
        packs = [
            list(next(p for p in player["packs"] if p["pack"] == pack_num)["cards"])
            for player in sealed_players
        ]
        run_pack(pack_num, packs, drafted, logs_dir)

    # ── Save final drafted pools ──────────────────────────────
    print(f"\n{'═'*58}")
    print("  DRAFT COMPLETE")
    print(f"{'═'*58}\n")

    for i, cards in enumerate(drafted):
        label     = "Human" if i == HUMAN else "AI"
        out_path  = drafted_dir / f"player_{i + 1}.json"
        out_path.write_text(json.dumps({
            "player":        i + 1,
            "is_human":      i == HUMAN,
            "total_drafted": len(cards),
            "cards":         cards,
        }, indent=2))
        print(f"  Player {i + 1} ({label}): {len(cards)} cards → drafted/player_{i + 1}.json")

    print(f"\n  All files saved under: {draft_dir}\n")


if __name__ == "__main__":
    main()
