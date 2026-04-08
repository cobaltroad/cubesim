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

PLAYER_COUNT = 4
PACK1_SIZE   = 15   # commander pack (maindeck=false)
PACK_SIZE    = 20   # maindeck packs 2-4 (maindeck=true)


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
        # Commander pack: 4 players × 15 cards from maindeck=false
        all_commanders = _fetch_cards(conn, maindeck=False, limit=PLAYER_COUNT * PACK1_SIZE)
        # Maindeck packs 2-4: 4 players × 3 packs × 20 cards from maindeck=true
        all_main = _fetch_cards(conn, maindeck=True, limit=PLAYER_COUNT * 3 * PACK_SIZE)
    finally:
        conn.close()

    random.shuffle(all_commanders)
    random.shuffle(all_main)

    players = []
    for p in range(PLAYER_COUNT):
        pack1 = all_commanders[p * PACK1_SIZE : (p + 1) * PACK1_SIZE]
        packs = [{"pack": 1, "cards": pack1}]

        for pack_num in range(2, 5):
            idx        = p * 3 + (pack_num - 2)
            pack_cards = all_main[idx * PACK_SIZE : (idx + 1) * PACK_SIZE]
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
