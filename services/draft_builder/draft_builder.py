#!/usr/bin/env python3
"""
Draft builder for cubesim.

Constructs a sealed draft from the card database:
  - 4 players
  - Pack 1 (15 cards each): 60 random sideboard cards (maindeck=false), 15 per player
  - Packs 2-4 (20 cards each): 2 sideboard + 18 maindeck cards per pack
  - Total per player: 15 + 20 + 20 + 20 = 75 cards

Output saved to: drafts/draft-<timestamp>-<uuid>/sealed/
  manifest.json   — full sealed pool data
  player_N.json   — per-player card lists (N = 1..4)
"""

import json
import os
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://cubesim:cubesim@localhost:5432/cubesim")
OUTPUT_BASE = Path(os.getenv("OUTPUT_DIR", "drafts"))
PLAYER_COUNT = 4
PACK1_SIZE = 15
PACK_SIDE_COUNT = 2   # sideboard cards per pack 2-4
PACK_MAIN_COUNT = 18  # maindeck cards per pack 2-4
PACK_SIZE = PACK_SIDE_COUNT + PACK_MAIN_COUNT  # 20


def fetch_cards(conn, maindeck: bool, limit: int) -> list[dict]:
    """Fetch `limit` random cached cards filtered by maindeck flag."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, name, set_code, collector_number,
                   image_uri_small, image_uri_normal, image_uri_large,
                   maindeck,
                   COALESCE(
                       NULLIF(scryfall_data->>'mana_cost', ''),
                       scryfall_data->'card_faces'->0->>'mana_cost'
                   ) AS mana_cost,
                   COALESCE(
                       NULLIF(scryfall_data->>'type_line', ''),
                       scryfall_data->'card_faces'->0->>'type_line'
                   ) AS type_line,
                   COALESCE(
                       NULLIF(scryfall_data->>'oracle_text', ''),
                       scryfall_data->'card_faces'->0->>'oracle_text'
                   ) AS oracle_text,
                   scryfall_data->>'power'     AS power,
                   scryfall_data->>'toughness' AS toughness
            FROM cards
            WHERE image_cached = TRUE AND maindeck = %s
            ORDER BY RANDOM()
            LIMIT %s
            """,
            (maindeck, limit),
        )
        rows = cur.fetchall()
    if len(rows) < limit:
        raise RuntimeError(
            f"Not enough {'maindeck' if maindeck else 'sideboard'} cards in cache: "
            f"need {limit}, have {len(rows)}"
        )
    return [dict(r) for r in rows]


def build_draft() -> dict:
    conn = psycopg2.connect(DATABASE_URL)
    try:
        # --- fetch all needed cards in one query per type to guarantee no duplicates ---
        # Sideboard total: 4×15 (pack 1) + 4×3×2 (packs 2-4) = 60 + 24 = 84
        side_total = PLAYER_COUNT * PACK1_SIZE + PLAYER_COUNT * 3 * PACK_SIDE_COUNT
        all_side = fetch_cards(conn, maindeck=False, limit=side_total)

        # Maindeck total: 4×3×18 (packs 2-4) = 216
        main_total = PLAYER_COUNT * 3 * PACK_MAIN_COUNT
        all_main = fetch_cards(conn, maindeck=True, limit=main_total)
    finally:
        conn.close()

    random.shuffle(all_side)
    random.shuffle(all_main)

    # Slice the single sideboard pool into pack-1 cards and packs-2-4 cards
    side_pack1  = all_side[:PLAYER_COUNT * PACK1_SIZE]
    side_packs24 = all_side[PLAYER_COUNT * PACK1_SIZE:]

    players = []
    for p in range(PLAYER_COUNT):
        # Pack 1: slice 15 sideboard cards
        pack1_start = p * PACK1_SIZE
        pack1 = side_pack1[pack1_start : pack1_start + PACK1_SIZE]

        packs = [{"pack": 1, "cards": pack1}]

        # Packs 2-4
        for pack_num in range(2, 5):
            idx = (p * 3 + (pack_num - 2))  # 0..11 across all players/packs
            side_start = idx * PACK_SIDE_COUNT
            main_start = idx * PACK_MAIN_COUNT

            side_cards = side_packs24[side_start : side_start + PACK_SIDE_COUNT]
            main_cards = all_main[main_start : main_start + PACK_MAIN_COUNT]

            pack_cards = side_cards + main_cards
            random.shuffle(pack_cards)  # mix sideboard and maindeck within pack
            packs.append({"pack": pack_num, "cards": pack_cards})

        total = sum(len(pk["cards"]) for pk in packs)
        players.append({
            "player": p + 1,
            "total_cards": total,
            "packs": packs,
        })

    return {
        "draft_id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "player_count": PLAYER_COUNT,
        "players": players,
    }


def save_draft(draft: dict) -> Path:
    ts = datetime.fromisoformat(draft["created_at"]).strftime("%Y%m%d-%H%M%S")
    sealed_dir = OUTPUT_BASE / f"draft-{ts}-{draft['draft_id']}" / "sealed"
    sealed_dir.mkdir(parents=True, exist_ok=True)

    # Full manifest
    (sealed_dir / "manifest.json").write_text(json.dumps(draft, indent=2))

    # Per-player files
    for player in draft["players"]:
        (sealed_dir / f"player_{player['player']}.json").write_text(json.dumps(player, indent=2))

    return sealed_dir


def main() -> None:
    print("Building draft...")
    draft = build_draft()

    out_dir = save_draft(draft)
    print(f"Draft saved to: {out_dir}")

    for player in draft["players"]:
        pack_summary = ", ".join(
            f"pack{pk['pack']}={len(pk['cards'])}" for pk in player["packs"]
        )
        print(f"  Player {player['player']}: {player['total_cards']} cards ({pack_summary})")


if __name__ == "__main__":
    main()
