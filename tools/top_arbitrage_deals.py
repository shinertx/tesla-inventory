#!/usr/bin/env python3
"""Generate ranked Top Arbitrage Deals from .data/arbitrage_opportunities.json and inventory.json."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_top_deals(
    min_spread_dollars: int = 4000,
    models: tuple[str, ...] | None = None,
    only_live_marked_up: bool = True,
    limit: int = 50,
) -> list[dict]:
    inv_path = ROOT / "inventory.json"
    arb_path = ROOT / ".data" / "arbitrage_opportunities.json"

    pub_items = {x["vin"]: x for x in json.loads(inv_path.read_text())["items"]}
    arb_items = json.loads(arb_path.read_text())["items"]

    deals: list[dict] = []
    for a in arb_items:
        vin = a["vin"]
        p = pub_items.get(vin)
        if not p:
            continue
        if models and p["model"] not in models:
            continue

        source_ask_dollars = a["source_asking_cents"] // 100
        live_price_dollars = int(round(p["display_price"]))
        proposed_dollars = a["proposed_retail_cents"] // 100
        ref_dollars = (a.get("reference_cents") or 0) // 100

        live_spread_dollars = live_price_dollars - source_ask_dollars
        modeled_spread_dollars = a["modeled_gross_spread_cents"] // 100
        effective_spread = live_spread_dollars if only_live_marked_up else modeled_spread_dollars

        if effective_spread < min_spread_dollars:
            continue

        # 4-layer total gross profit estimate:
        # Layer 1: Upfront mispriced markup (effective_spread)
        # Layer 2: Wholesale negotiation discount ($1,000 conservative)
        # Layer 3: AutoFi / CUDL lender reserve ($800 conservative)
        # Layer 4: Shipping safety buffer ($200)
        total_4layer_profit = effective_spread + 1000 + 800 + 200

        deals.append(
            {
                "vin": vin,
                "year": p["year"],
                "model": p["model"],
                "trim": p["trim"],
                "mileage": p["mileage"],
                "state": p.get("state") or "US",
                "source_dealer": a.get("source_dealer") or "Source Dealer",
                "source_url": a.get("source_url") or "",
                "source_ask_dollars": source_ask_dollars,
                "live_price_dollars": live_price_dollars,
                "proposed_dollars": proposed_dollars,
                "ref_dollars": ref_dollars,
                "buyer_savings_dollars": max(0, ref_dollars - live_price_dollars),
                "upfront_spread_dollars": effective_spread,
                "total_4layer_profit_dollars": total_4layer_profit,
                "review_flags": a.get("review_flags") or [],
            }
        )

    deals.sort(key=lambda d: (d["upfront_spread_dollars"], -d["live_price_dollars"]), reverse=True)
    return deals[:limit]


def write_markdown_report(output_path: Path, min_spread_dollars: int = 4000) -> dict:
    all_live = load_top_deals(min_spread_dollars=min_spread_dollars, only_live_marked_up=True, limit=25)
    m3_my_live = load_top_deals(
        min_spread_dollars=min_spread_dollars,
        models=("Model 3", "Model Y"),
        only_live_marked_up=True,
        limit=25,
    )

    lines = [
        "# Top Mispriced Tesla Arbitrage Deals (`+$4,000+` Upfront Spread)",
        "",
        "Generated from live [`inventory.json`](../inventory.json) and [`.data/arbitrage_opportunities.json`](../.data/arbitrage_opportunities.json).",
        "- **Buyer Discount Policy (`PricingPolicy.buyer_savings_cents`):** Buyer still saves **`$1,500` below peer market benchmark**.",
        "- **4-Layer Profit Formula:** `Upfront Mispriced Spread` + `$1,000 Wholesale Negotiation` + `$800 Lender Reserve` + `$200 Shipping Buffer`.",
        "",
        "## 1. Fast-Moving Volume Picks: Model 3 & Model Y (`+$4,000+` Upfront Markup)",
        "",
        "| VIN | Vehicle | Mi | St | Dealer Ask | Live V&V Price | Peer Ref | Buyer Saves | Upfront Spread | Est. 4-Layer Profit | Source Link |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for d in m3_my_live:
        link = f"[Listing]({d['source_url']})" if d["source_url"] else "N/A"
        lines.append(
            f"| `{d['vin']}` | {d['year']} {d['model']} {d['trim']} | {d['mileage']:,} | {d['state']} "
            f"| `${d['source_ask_dollars']:,}` | **`${d['live_price_dollars']:,}`** | `${d['ref_dollars']:,}` "
            f"| **`${d['buyer_savings_dollars']:,}`** | **`+${d['upfront_spread_dollars']:,}`** | **`+${d['total_4layer_profit_dollars']:,}`** | {link} |"
        )

    lines.extend(
        [
            "",
            "## 2. Highest Dollar Spread Across All Models (Model S / X / Cybertruck / Y)",
            "",
            "| VIN | Vehicle | Mi | St | Dealer Ask | Live V&V Price | Peer Ref | Buyer Saves | Upfront Spread | Est. 4-Layer Profit | Source Link |",
            "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for d in all_live:
        link = f"[Listing]({d['source_url']})" if d["source_url"] else "N/A"
        lines.append(
            f"| `{d['vin']}` | {d['year']} {d['model']} {d['trim']} | {d['mileage']:,} | {d['state']} "
            f"| `${d['source_ask_dollars']:,}` | **`${d['live_price_dollars']:,}`** | `${d['ref_dollars']:,}` "
            f"| **`${d['buyer_savings_dollars']:,}`** | **`+${d['upfront_spread_dollars']:,}`** | **`+${d['total_4layer_profit_dollars']:,}`** | {link} |"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n")
    return {"all_count": len(all_live), "m3_my_count": len(m3_my_live)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Filter top mispriced Tesla arbitrage deals.")
    parser.add_argument("--min-spread", type=int, default=4000, help="Minimum upfront spread in dollars")
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "TOP_ARBITRAGE_DEALS.md")
    args = parser.parse_args()
    stats = write_markdown_report(args.out, min_spread_dollars=args.min_spread)
    print(f"Wrote {args.out} (Top M3/MY: {stats['m3_my_count']}, Top All: {stats['all_count']})")


if __name__ == "__main__":
    main()
