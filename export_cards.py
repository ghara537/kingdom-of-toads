"""Export the card deck to CSV, for the balance spreadsheet.

    python export_cards.py            # writes cards.csv
    python export_cards.py -          # writes to stdout

The CSV mirrors ``config.CARD_DEFS`` exactly, so re-running it after a tuning
pass regenerates a sheet that matches the code. The `notes` column is left
empty on purpose: it is yours, and nothing reads it back automatically.

To add a card: add a row here or in the sheet, then add the matching entry to
``config.CARD_DEFS``. The columns line up one-to-one with that dict.
"""

from __future__ import annotations

import csv
import io
import sys

import bots
import cards as card_lib
import config

COLUMNS = [
    "id",
    "name",
    "development",
    "group",
    "vp",
    "copies_2_3p",
    "copies_4_6p",
    "requirement_area",
    "requirement_toads",
    "effect_kind",
    "effect_amount",
    "conditional_metric",
    "conditional_per",
    "conditional_vp",
    "ability",
    "ability_cost",
    "summary",
    "bot_base_value",
    "notes",
]


def rows() -> list[dict]:
    low = config.CARD_COPIES_LOW_COUNT
    high = config.CARD_COPIES_HIGH_COUNT
    out = []
    for card in card_lib.CARDS.values():
        req_area, req_toads = card.requirement or ("", "")
        kind, amount = card.effect or ("", "")
        metric, per, cond_vp = card.conditional or ("", "", "")
        ability, ability_cost = card.ability or ("", "")
        out.append({
            "id": card.id,
            "name": card.name,
            "development": card.development,
            "group": card.group,
            "vp": card.vp,
            "copies_2_3p": low[card.group],
            "copies_4_6p": high[card.group],
            "requirement_area": req_area,
            "requirement_toads": req_toads,
            "effect_kind": kind,
            "effect_amount": amount,
            "conditional_metric": metric,
            "conditional_per": per,
            "conditional_vp": cond_vp,
            "ability": ability,
            "ability_cost": ability_cost,
            "summary": card.describe(),
            "bot_base_value": bots.BASE_CARD_VALUE.get(card.id, ""),
            "notes": "",
        })
    return out


def totals_row() -> dict:
    data = rows()
    blank = {c: "" for c in COLUMNS}
    blank.update({
        "id": "TOTAL",
        "name": f"{len(data)} card types",
        "copies_2_3p": sum(r["copies_2_3p"] for r in data),
        "copies_4_6p": sum(r["copies_4_6p"] for r in data),
        "summary": "cards in the deck at each player count",
    })
    return blank


def to_csv() -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    order = {
        config.GROUP_ENGINE: 0,
        config.GROUP_ACTIVATED: 1,
        config.GROUP_INSTANT: 2,
        config.GROUP_FLAT: 3,
        config.GROUP_CONDITIONAL: 4,
    }
    stage = {config.VILLAGE: 0, config.CITY: 1}
    for row in sorted(
        rows(),
        key=lambda r: (stage[r["development"]], order[r["group"]], r["id"]),
    ):
        writer.writerow(row)
    writer.writerow(totals_row())
    return buffer.getvalue()


if __name__ == "__main__":
    text = to_csv()
    if len(sys.argv) > 1 and sys.argv[1] == "-":
        sys.stdout.write(text)
    else:
        with open("cards.csv", "w", encoding="utf-8") as handle:
            handle.write(text)
        print(f"wrote cards.csv — {len(rows())} card types")
