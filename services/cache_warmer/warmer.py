#!/usr/bin/env python3
"""
Cache warmer for cubesim.

Reads a card list from INPUT_FILE (default: /input/commander-cube.txt),
queries the Scryfall API for each card, downloads card images to a local
volume, and upserts card records (keyed by Scryfall UUID) into PostgreSQL.

Scryfall rate-limit policy: no more than 10 requests/second; a 100 ms delay
between every outbound request keeps well within that budget.
"""

import json
import logging
import os
import re
import time
import uuid
from pathlib import Path

import httpx
import psycopg2
import psycopg2.extras

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

SCRYFALL_API = "https://api.scryfall.com"
RATE_DELAY = 0.1          # 100 ms between every Scryfall request
IMAGE_DIR = Path(os.getenv("IMAGE_CACHE_DIR", "/cache/images"))
INPUT_FILE = Path(os.getenv("INPUT_FILE", "/input/commander-cube.txt"))
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://cubesim:cubesim@db:5432/cubesim")


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_card_list(filepath: Path) -> list:
    """Return an ordered list of (name, maindeck) tuples with no duplicates."""
    cards = []
    seen = set()
    maindeck = True
    with open(filepath) as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            if line.upper().startswith("SIDEBOARD"):
                maindeck = False
                continue
            # Accept "1 Card Name" or bare "Card Name"
            m = re.match(r"^\d+\s+(.+)$", line)
            name = m.group(1).strip() if m else line
            if name and name not in seen:
                seen.add(name)
                cards.append((name, maindeck))
    return cards


# ---------------------------------------------------------------------------
# Scryfall helpers
# ---------------------------------------------------------------------------

def scryfall_get(client: httpx.Client, url: str, **kwargs) -> httpx.Response:
    """
    GET a Scryfall URL with automatic 429 back-off.
    Respects the Retry-After header; falls back to doubling the base delay.
    """
    delay = RATE_DELAY
    while True:
        resp = client.get(url, **kwargs)
        if resp.status_code != 429:
            return resp
        retry_after = float(resp.headers.get("Retry-After", delay))
        log.warning("429 from Scryfall — backing off %.1f s", retry_after)
        time.sleep(retry_after)
        delay = min(delay * 2, 60.0)


def fetch_card(client: httpx.Client, name: str) -> dict:
    """Query Scryfall for a card by exact name; returns card dict or None."""
    try:
        resp = scryfall_get(
            client,
            f"{SCRYFALL_API}/cards/named",
            params={"exact": name},
        )
        if resp.status_code == 404:
            log.warning("Not found on Scryfall: %r", name)
            return None
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        log.error("HTTP %s fetching %r: %s", exc.response.status_code, name, exc)
        return None
    except httpx.RequestError as exc:
        log.error("Request error fetching %r: %s", name, exc)
        return None


def resolve_image_uris(card: dict) -> dict:
    """
    Return the image_uris dict for a card.
    Falls back to the front face for double-faced cards.
    """
    if card.get("image_uris"):
        return card["image_uris"]
    faces = card.get("card_faces", [])
    if faces and faces[0].get("image_uris"):
        return faces[0]["image_uris"]
    return {}


def download_image(client: httpx.Client, card_id: str, url: str) -> bool:
    """Download the normal-size image; skip if already cached. Returns success."""
    dest = IMAGE_DIR / f"{card_id}.jpg"
    if dest.exists():
        log.debug("Image already cached: %s", card_id)
        return True
    try:
        resp = scryfall_get(client, url, follow_redirects=True)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        log.debug("Cached image: %s", dest.name)
        return True
    except Exception as exc:
        log.error("Failed to download image for %s: %s", card_id, exc)
        return False


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def delete_removed_cards(conn, current_names: set) -> None:
    """Delete rows for cards that are no longer in the card list."""
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM cards")
        db_names = {row[0] for row in cur.fetchall()}
    removed = db_names - current_names
    if not removed:
        log.info("No removed cards to delete.")
        return
    with conn.cursor() as cur:
        cur.execute("DELETE FROM cards WHERE name = ANY(%s)", (list(removed),))
    conn.commit()
    log.info("Deleted %d removed card(s): %s", len(removed), ", ".join(sorted(removed)))


def already_cached(conn, name: str) -> bool:
    """Return True if a card is already in the DB with image_cached = TRUE."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM cards WHERE name = %s AND image_cached = TRUE LIMIT 1",
            (name,),
        )
        return cur.fetchone() is not None


def upsert_card(conn, card: dict, image_cached: bool, maindeck: bool) -> None:
    uris = resolve_image_uris(card)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO cards (
                id, name, set_code, collector_number,
                image_uri_small, image_uri_normal, image_uri_large,
                image_cached, maindeck, scryfall_data
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name             = EXCLUDED.name,
                set_code         = EXCLUDED.set_code,
                collector_number = EXCLUDED.collector_number,
                image_uri_small  = EXCLUDED.image_uri_small,
                image_uri_normal = EXCLUDED.image_uri_normal,
                image_uri_large  = EXCLUDED.image_uri_large,
                image_cached     = EXCLUDED.image_cached,
                maindeck         = EXCLUDED.maindeck,
                scryfall_data    = EXCLUDED.scryfall_data,
                updated_at       = NOW()
            """,
            (
                str(uuid.UUID(card["id"])),
                card["name"],
                card.get("set"),
                card.get("collector_number"),
                uris.get("small"),
                uris.get("normal"),
                uris.get("large"),
                image_cached,
                maindeck,
                psycopg2.extras.Json(card),
            ),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    log.info("Reading card list from %s", INPUT_FILE)
    cards = parse_card_list(INPUT_FILE)
    log.info("Found %d unique cards to process", len(cards))

    conn = psycopg2.connect(DATABASE_URL)

    current_names = {name for name, _ in cards}
    delete_removed_cards(conn, current_names)

    headers = {
        "User-Agent": "cubesim-cache-warmer/1.0",
        "Accept": "application/json",
    }
    with httpx.Client(headers=headers, timeout=30.0) as client:
        for i, (name, maindeck) in enumerate(cards, 1):
            if already_cached(conn, name):
                log.info("[%d/%d] %s — already cached, skipping", i, len(cards), name)
                continue

            log.info("[%d/%d] %s (%s)", i, len(cards), name, "main" if maindeck else "side")

            card_data = fetch_card(client, name)
            time.sleep(RATE_DELAY)  # honour Scryfall rate limit

            if card_data is None:
                continue

            image_cached = False
            uris = resolve_image_uris(card_data)
            if normal_url := uris.get("normal"):
                image_cached = download_image(client, card_data["id"], normal_url)
                time.sleep(RATE_DELAY)  # image host also counts toward rate limit

            upsert_card(conn, card_data, image_cached, maindeck)

    conn.close()
    log.info("Cache warming complete.")


if __name__ == "__main__":
    main()
