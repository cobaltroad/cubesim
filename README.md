# Commander Cube Draft Simulator

A web-based draft simulator for a curated Commander cube. One human player drafts against three AI opponents. The resulting 75-card pool is intended for Commander deck construction.

---

## Draft Structure

Each player opens **4 packs** and ends with **75 cards**.

### Commander Pack (Pack 1)

- **15 cards** drawn from the Commander pool
- **1 pick per pass**
- Packs rotate **left**
- This is where you select your Commander

### Main Deck Packs (Packs 2–4)

- **20 cards** drawn from the main deck pool
- **2 picks per pass**
- Pack direction alternates: Pack 2 rotates **right**, Pack 3 rotates **left**, Pack 4 rotates **right**

---

## Card Pools

Cards in the cube are divided into two pools:

| Pool | `maindeck` flag | Size | Used in |
|------|----------------|------|---------|
| Commander pool | `false` | 80 cards | Pack 1 only |
| Main deck pool | `true` | 340 cards | Packs 2–4 only |

---

## AI Strategy

The three AI opponents evaluate cards by **EDHREC rank** — lower rank (more popular) is picked first. Unranked cards are treated as least desirable.

---

## Playing a Draft

The simulator is available at [cube.cardtrak.app](https://cube.cardtrak.app).

1. Click **Start Draft** to build a new sealed pool and begin
2. During the **Commander Pack**, click a card to immediately pick it
3. During **Packs 2–4**, select 2 cards then click **Confirm Pick**
4. Hover over any card to see its oracle text and stats
5. Use the **Drafted** button to review your picks at any time
6. When all packs are complete, view your full pool and download it as a text file for import into **Moxfield**

---

## Project Layout

```
input/
  commander-cube.txt     Card list (SIDEBOARD section = Commander pool)

services/
  cache_warmer/          Fetches card data and images from Scryfall
  draft_builder/         CLI tool to generate a sealed pool
  draft_runner/          CLI tool for terminal-based drafting
  ui/                    FastAPI + vanilla JS web interface

db/
  init.sql               PostgreSQL schema

drafts/                  Generated draft directories (not committed)
```

## Operations

```bash
make ingest    # Fetch/update card data and images from Scryfall
make draft     # Build a sealed pool and run a draft in the terminal
```

The web UI builds sealed pools and runs drafts directly via the browser.
