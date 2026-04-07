"""
Draft state machine for the web UI.
Implements the same rules as draft_runner.py but persists state to state.json.
"""

import json
import os
from pathlib import Path

N_PLAYERS  = 4
HUMAN      = 0
PICKS_PACK = {1: 1, 2: 2, 3: 2, 4: 2}
# +1 = left (player i passes to i+1), -1 = right (i passes to i-1)
DIRECTION  = {1: +1, 2: -1, 3: +1, 4: -1}


# ─────────────────────────────────────────────────────────────
# Persistence
# ─────────────────────────────────────────────────────────────

def load_state(draft_dir: Path) -> dict | None:
    path = draft_dir / "state.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def save_state(draft_dir: Path, state: dict) -> None:
    """Atomic write: write to .tmp then rename."""
    path = draft_dir / "state.json"
    tmp  = draft_dir / "state.json.tmp"
    tmp.write_text(json.dumps(state, indent=2))
    os.replace(tmp, path)


# ─────────────────────────────────────────────────────────────
# Sealed pool loading
# ─────────────────────────────────────────────────────────────

def _load_sealed(draft_dir: Path) -> list[dict]:
    """Return list of 4 player dicts from sealed/player_N.json (1-indexed)."""
    players = []
    for i in range(1, N_PLAYERS + 1):
        path = draft_dir / "sealed" / f"player_{i}.json"
        players.append(json.loads(path.read_text()))
    return players


def _extract_pack(sealed_players: list[dict], pack_num: int) -> list[list[dict]]:
    """Return 4 card lists, one per player, for the given pack number."""
    return [
        list(next(p for p in player["packs"] if p["pack"] == pack_num)["cards"])
        for player in sealed_players
    ]


# ─────────────────────────────────────────────────────────────
# Initialisation
# ─────────────────────────────────────────────────────────────

def init_state(draft_dir: Path) -> dict:
    """Initialise a fresh state from the sealed pool. Does NOT save to disk."""
    manifest = json.loads((draft_dir / "sealed" / "manifest.json").read_text())
    draft_id = manifest["draft_id"]

    sealed_players = _load_sealed(draft_dir)
    packs = _extract_pack(sealed_players, 1)

    return {
        "draft_id":             draft_id,
        "status":               "in_progress",
        "current_pack":         1,
        "current_pass":         1,
        "picks_per_pass":       PICKS_PACK[1],
        "direction":            DIRECTION[1],
        "human_picks_remaining": min(PICKS_PACK[1], len(packs[HUMAN])),
        "current_player_packs": packs,
        "drafted": {str(i): [] for i in range(N_PLAYERS)},
    }


# ─────────────────────────────────────────────────────────────
# AI strategy
# ─────────────────────────────────────────────────────────────

def _ai_pick(pack: list[dict], n_picks: int) -> list[dict]:
    sorted_pack = sorted(pack, key=lambda c: c.get("edhrec_rank") or 999999)
    return sorted_pack[: min(n_picks, len(sorted_pack))]


# ─────────────────────────────────────────────────────────────
# Finalisation
# ─────────────────────────────────────────────────────────────

def finalize_draft(draft_dir: Path, state: dict) -> None:
    """Write drafted/player_N.json for all 4 players."""
    drafted_dir = draft_dir / "drafted"
    drafted_dir.mkdir(exist_ok=True)
    for i in range(N_PLAYERS):
        cards = state["drafted"][str(i)]
        (drafted_dir / f"player_{i + 1}.json").write_text(json.dumps({
            "player":        i + 1,
            "is_human":      i == HUMAN,
            "total_drafted": len(cards),
            "cards":         cards,
        }, indent=2))


# ─────────────────────────────────────────────────────────────
# Core: apply a human pick
# ─────────────────────────────────────────────────────────────

def apply_human_pick(state: dict, card_id: str, draft_dir: Path) -> dict:
    """
    Remove card_id from the human's pack, add it to their drafted pile.
    When the human finishes their picks for this pass:
      - Run AI picks for players 1-3.
      - Rotate packs.
      - Advance to next pass or pack, or mark complete.
    Saves state.json atomically before returning.
    """
    packs = state["current_player_packs"]

    # --- Remove the picked card from the human's pack ---
    human_pack = packs[HUMAN]
    card = next((c for c in human_pack if c["id"] == card_id), None)
    if card is None:
        raise ValueError(f"Card {card_id} not found in human pack")
    human_pack.remove(card)
    state["drafted"]["0"].append(card)
    state["human_picks_remaining"] -= 1

    if state["human_picks_remaining"] > 0:
        # Human still needs to pick more cards this pass — just save and return.
        save_state(draft_dir, state)
        return state

    # --- Human is done picking this pass; run AI picks then rotate ---
    _run_ai_and_rotate(state, draft_dir)
    save_state(draft_dir, state)
    return state


def _run_ai_and_rotate(state: dict, draft_dir: Path) -> None:
    """
    Complete the current pass: AI picks for players 1-3, rotate packs, then
    advance to next pass/pack or mark the draft complete.
    Loops automatically if the human's new pack is empty (edge-case safety).
    """
    while True:
        packs         = state["current_player_packs"]
        n_picks       = state["picks_per_pass"]
        direction     = state["direction"]

        # AI picks
        for player_idx in range(1, N_PLAYERS):
            if not packs[player_idx]:
                continue
            picks = _ai_pick(packs[player_idx], n_picks)
            for c in picks:
                packs[player_idx].remove(c)
            state["drafted"][str(player_idx)].extend(picks)

        # Rotate packs: player i receives what player (i - direction) % 4 had
        state["current_player_packs"] = [
            packs[(i - direction) % N_PLAYERS] for i in range(N_PLAYERS)
        ]
        packs = state["current_player_packs"]

        if not any(packs):
            # All packs exhausted — advance to next pack or finish
            next_pack = state["current_pack"] + 1
            if next_pack > 4:
                state["status"] = "complete"
                finalize_draft(draft_dir, state)
                return
            else:
                sealed_players = _load_sealed(draft_dir)
                new_packs = _extract_pack(sealed_players, next_pack)
                state["current_pack"]          = next_pack
                state["current_pass"]          = 1
                state["picks_per_pass"]        = PICKS_PACK[next_pack]
                state["direction"]             = DIRECTION[next_pack]
                state["current_player_packs"]  = new_packs
                packs = new_packs
                # Fall through to check human's new pack below
        else:
            state["current_pass"] += 1

        # Set how many picks the human needs this pass
        human_has = len(packs[HUMAN])
        if human_has > 0:
            state["human_picks_remaining"] = min(state["picks_per_pass"], human_has)
            return  # Human has cards — stop and let them pick

        # Human's pack is empty but others are not; run another AI-only pass
        # (rare edge case at end of pack with uneven distribution)
        if not any(packs):
            # Nothing left anywhere — loop will detect and finalize
            continue
        # Skip human this pass and let AIs pick
        # human_picks_remaining stays 0; loop continues
