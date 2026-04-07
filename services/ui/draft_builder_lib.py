"""
Draft builder logic extracted for use by the UI service.
Mirrors draft_builder.py but exposes a callable function rather than a CLI.
"""

import json
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras

PLAYER_COUNT    = 4
PACK1_SIZE      = 15
PACK_SIDE_COUNT = 2
PACK_MAIN_COUNT = 18
PACK_SIZE       = PACK_SIDE_COUNT + PACK_MAIN_COUNT  # 20


def _fetch_cards(conn, maindeck: bool, limit: int) -> list[dict]:
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
                   scryfall_data->>'power'       AS power,
                   scryfall_data->>'toughness'   AS toughness,
                   (scryfall_data->>'edhrec_rank')::int AS edhrec_rank
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


def _build_draft(db_url: str) -> dict:
    conn = psycopg2.connect(db_url)
    try:
        side_total = PLAYER_COUNT * PACK1_SIZE + PLAYER_COUNT * 3 * PACK_SIDE_COUNT
        all_side   = _fetch_cards(conn, maindeck=False, limit=side_total)
        main_total = PLAYER_COUNT * 3 * PACK_MAIN_COUNT
        all_main   = _fetch_cards(conn, maindeck=True, limit=main_total)
    finally:
        conn.close()

    random.shuffle(all_side)
    random.shuffle(all_main)

    side_pack1   = all_side[: PLAYER_COUNT * PACK1_SIZE]
    side_packs24 = all_side[PLAYER_COUNT * PACK1_SIZE :]

    players = []
    for p in range(PLAYER_COUNT):
        pack1_start = p * PACK1_SIZE
        pack1       = side_pack1[pack1_start : pack1_start + PACK1_SIZE]
        packs       = [{"pack": 1, "cards": pack1}]

        for pack_num in range(2, 5):
            idx        = p * 3 + (pack_num - 2)
            side_cards = side_packs24[idx * PACK_SIDE_COUNT : (idx + 1) * PACK_SIDE_COUNT]
            main_cards = all_main[idx * PACK_MAIN_COUNT   : (idx + 1) * PACK_MAIN_COUNT]
            pack_cards = side_cards + main_cards
            random.shuffle(pack_cards)
            packs.append({"pack": pack_num, "cards": pack_cards})

        players.append({
            "player":      p + 1,
            "total_cards": sum(len(pk["cards"]) for pk in packs),
            "packs":       packs,
        })

    return {
        "draft_id":     str(uuid.uuid4()),
        "created_at":   datetime.now(timezone.utc).isoformat(),
        "player_count": PLAYER_COUNT,
        "players":      players,
    }


def build_and_save_draft(db_url: str, output_dir: Path) -> Path:
    """Build a new sealed pool and write it to output_dir. Returns the draft directory Path."""
    draft = _build_draft(db_url)
    ts    = datetime.fromisoformat(draft["created_at"]).strftime("%Y%m%d-%H%M%S")

    sealed_dir = output_dir / f"draft-{ts}-{draft['draft_id']}" / "sealed"
    sealed_dir.mkdir(parents=True, exist_ok=True)

    (sealed_dir / "manifest.json").write_text(json.dumps(draft, indent=2))
    for player in draft["players"]:
        (sealed_dir / f"player_{player['player']}.json").write_text(
            json.dumps(player, indent=2)
        )

    return sealed_dir.parent
