#!/usr/bin/env python3
"""Real-time & scheduled pipeline jobs for Volts & VINs.

Breaks the marketplace lifecycle into 5 discrete, auditable jobs:
1. discover_vehicles   — Pulls fresh Tesla VIN observations from live sources (Autolist, CarGurus, TrueCar, Carvana).
2. enrich_media        — Backfills VIN-bound multi-photo galleries for newly discovered vehicles.
3. reprice_and_build   — Recomputes peer benchmarks, dynamic 50/50 buyer-seller savings, Top Arbitrage Deals, and 197 HTML/AI pages.
4. publish_and_index   — Pushes updated catalog to GitHub Pages (voltsandvins.com) and pings IndexNow (Bing/ChatGPT/Perplexity).
5. match_customer_orders — Real-time (60s) matcher that pairs incoming customer VIN requests in orders.db with private source dealer links & arbitrage spread.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.collect import source_url, parse_source
from tools.inventory import ingest, export
from tools.build import build as build_catalog
from tools.top_arbitrage_deals import load_top_deals, write_markdown_report
from tools.indexnow import ping_indexnow


DEFAULT_PARTITIONS = [
    ("cargurus", "Model Y", 2024, 1),
    ("cargurus", "Model Y", 2023, 1),
    ("cargurus", "Model 3", 2024, 1),
    ("cargurus", "Model 3", 2023, 1),
    ("autolist", "Model Y", 2024, 1),
    ("autolist", "Model 3", 2024, 1),
    ("truecar", "Model Y", 2024, 1),
    ("carvana", "Model Y", 2023, 1),
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_job_status(status_file: Path, job_name: str, payload: dict) -> dict:
    status_file.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if status_file.exists():
        try:
            existing = json.loads(status_file.read_text())
        except Exception:
            existing = {}
    jobs = existing.get("jobs", {})
    jobs[job_name] = {"updated_at": _utc_now(), **payload}
    existing["jobs"] = jobs
    existing["last_updated"] = _utc_now()
    status_file.write_text(json.dumps(existing, indent=2))
    return existing


def job_discover_vehicles(
    *,
    db_path: Path = ROOT / ".data/inventory.db",
    snapshot_path: Path = ROOT / ".data/source_snapshot.json",
    partitions: list[tuple[str, str, int, int]] | None = None,
    status_file: Path = ROOT / ".data/jobs_status.json",
) -> dict:
    """Job 1: Collect fresh Tesla listings across sources without discarding existing snapshot on 403/rate-limit."""
    from curl_cffi import requests

    partitions = partitions or DEFAULT_PARTITIONS
    now = _utc_now()
    accepted_total = 0
    partition_results = []
    for source, model, year, pages in partitions:
        for page in range(1, pages + 1):
            url = source_url(source, model, year, page)
            try:
                resp = requests.get(url, impersonate="chrome120", timeout=15)
                if resp.status_code != 200:
                    partition_results.append({
                        "source": source,
                        "model": model,
                        "year": year,
                        "page": page,
                        "ok": False,
                        "status_code": resp.status_code,
                    })
                    continue
                rows = parse_source(source, resp, model, year)
                valid_rows = [
                    r for r in rows
                    if r.get("source_url")
                    and r["source_url"].rstrip("/") not in ("https://www.autolist.com", "https://www.truecar.com")
                ]
                if valid_rows:
                    accepted = ingest(db_path, valid_rows, source, _utc_now(), complete=False)
                    accepted_total += accepted
                    partition_results.append({
                        "source": source,
                        "model": model,
                        "year": year,
                        "page": page,
                        "ok": True,
                        "fetched": len(valid_rows),
                        "accepted": accepted,
                    })
            except Exception as exc:
                partition_results.append({
                    "source": source,
                    "model": model,
                    "year": year,
                    "page": page,
                    "ok": False,
                    "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                })
    if accepted_total > 0 and db_path.exists():
        export(db_path, snapshot_path)
    result = {
        "ok": True,
        "accepted_observations": accepted_total,
        "partitions_checked": len(partition_results),
        "partitions_succeeded": sum(1 for p in partition_results if p.get("ok")),
        "details": partition_results,
    }
    _write_job_status(status_file, "1_discover_vehicles", result)
    return result


def job_enrich_media(
    *,
    snapshot_path: Path = ROOT / ".data/source_snapshot.json",
    gallery_path: Path = ROOT / "data/vehicle_photos.json",
    status_file: Path = ROOT / ".data/jobs_status.json",
    max_new_fetches: int = 10,
) -> dict:
    """Job 2: Ensure every VIN in source_snapshot has normalized photo galleries in vehicle_photos.json."""
    from tools.media import normalize_photos

    if not snapshot_path.exists():
        res = {"ok": False, "reason": "source_snapshot_missing"}
        _write_job_status(status_file, "2_enrich_media", res)
        return res
    rows = json.loads(snapshot_path.read_text()).get("items", [])
    galleries = json.loads(gallery_path.read_text()) if gallery_path.exists() else {}
    added = 0
    multi = 0
    for row in rows:
        vin = row.get("vin", "")
        if not vin:
            continue
        existing = galleries.get(vin, [])
        merged = normalize_photos(existing + row.get("photos", []))
        if not merged and row.get("photo_url"):
            merged = normalize_photos([row["photo_url"]])
        if merged and vin not in galleries:
            galleries[vin] = merged
            added += 1
        if len(galleries.get(vin, [])) > 1:
            multi += 1
    if added > 0:
        gallery_path.parent.mkdir(parents=True, exist_ok=True)
        gallery_path.write_text(json.dumps(galleries, separators=(",", ":")))
    result = {
        "ok": True,
        "catalog_vins_checked": len(rows),
        "galleries_total": len(galleries),
        "multi_photo_vins": multi,
        "new_galleries_indexed": added,
    }
    _write_job_status(status_file, "2_enrich_media", result)
    return result


def job_reprice_and_build(
    *,
    snapshot_path: Path = ROOT / ".data/source_snapshot.json",
    output_dir: Path = ROOT,
    min_spread_dollars: int = 3500,
    status_file: Path = ROOT / ".data/jobs_status.json",
) -> dict:
    """Job 3: Recompute peer benchmarks, dynamic 50/50 buyer-seller savings, static HTML, and Top Arbitrage Deals."""
    os.environ.setdefault("ENABLE_GITHUB_PAGES_CNAME", "true")
    os.environ.setdefault("BUYER_SURPLUS_SHARE", "0.5")
    manifest = build_catalog(source=snapshot_path, output=output_dir)
    docs_out = output_dir / "docs/TOP_ARBITRAGE_DEALS.md"
    write_markdown_report(docs_out, min_spread_dollars=min_spread_dollars)
    deals = load_top_deals(min_spread_dollars=min_spread_dollars, limit=1000)
    inv_data = json.loads((output_dir / "inventory.json").read_text())
    items = inv_data.get("items", [])
    price_finds = [x for x in items if (x.get("savings_amount") or 0) >= 500]
    unique_badges = len({x.get("savings_amount") for x in price_finds})
    result = {
        "ok": True,
        "published_count": manifest.get("published_count", len(items)),
        "price_finds_count": len(price_finds),
        "unique_savings_badges": unique_badges,
        "top_arbitrage_deals_over_3500": len(deals),
    }
    _write_job_status(status_file, "3_reprice_and_build", result)
    return result


def job_publish_and_index(
    *,
    repo_dir: Path = ROOT,
    ping_search_engines: bool = True,
    git_push: bool = False,
    status_file: Path = ROOT / ".data/jobs_status.json",
) -> dict:
    """Job 4: Optionally commit/push updated static catalog and ping IndexNow (Bing, ChatGPT, DuckDuckGo)."""
    indexnow_res = {}
    if ping_search_engines and (repo_dir / "sitemap.xml").exists():
        try:
            indexnow_res = ping_indexnow()
        except Exception as exc:
            indexnow_res = {"error": str(exc)[:160]}
    git_res = {"pushed": False}
    if git_push:
        try:
            status = subprocess.run(
                ["git", "status", "--porcelain", "inventory.json", "llms.txt", "llms-full.txt", "index.html", "deals", "models", "states", "years"],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            if status.stdout.strip():
                subprocess.run(
                    ["git", "add", "inventory.json", "llms.txt", "llms-full.txt", "index.html", "deals", "models", "states", "years", "docs/TOP_ARBITRAGE_DEALS.md"],
                    cwd=repo_dir,
                    check=True,
                )
                subprocess.run(
                    ["git", "commit", "-m", f"Automated catalog & dynamic pricing refresh ({_utc_now()[:16]}Z)"],
                    cwd=repo_dir,
                    check=True,
                )
                subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=repo_dir, check=True)
                git_res = {"pushed": True}
            else:
                git_res = {"pushed": False, "reason": "no_catalog_changes"}
        except Exception as exc:
            git_res = {"pushed": False, "error": str(exc)[:200]}
    result = {
        "ok": True,
        "indexnow": indexnow_res,
        "git": git_res,
    }
    _write_job_status(status_file, "4_publish_and_index", result)
    return result


def job_match_customer_orders(
    *,
    orders_db: Path = Path(os.getenv("ORDERS_DB", str(ROOT / ".data/orders.db"))),
    arb_path: Path = ROOT / ".data/arbitrage_opportunities.json",
    inv_path: Path = ROOT / "inventory.json",
    packets_out: Path = ROOT / ".data/deal_packets.json",
    status_file: Path = ROOT / ".data/jobs_status.json",
) -> dict:
    """Job 5: Real-time (60s) matcher pairing customer VIN reservation requests with private source dealer links & spreads."""
    if not orders_db.exists():
        res = {"ok": True, "orders_scanned": 0, "matched_packets": 0}
        _write_job_status(status_file, "5_match_customer_orders", res)
        return res

    arb_by_vin = {}
    if arb_path.exists():
        try:
            for item in json.loads(arb_path.read_text()).get("items", []):
                if item.get("vin"):
                    arb_by_vin[item["vin"]] = item
        except Exception:
            pass

    inv_by_vin = {}
    if inv_path.exists():
        try:
            for item in json.loads(inv_path.read_text()).get("items", []):
                if item.get("vin"):
                    inv_by_vin[item["vin"]] = item
        except Exception:
            pass

    packets = []
    with sqlite3.connect(orders_db) as conn:
        conn.row_factory = sqlite3.Row
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "orders" in tables:
            rows = conn.execute(
                "SELECT id, vin, state, customer, created_at FROM orders ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
            for r in rows:
                vin = r["vin"]
                try:
                    cust = json.loads(r["customer"] or "{}")
                except Exception:
                    cust = {}
                arb = arb_by_vin.get(vin, {})
                inv = inv_by_vin.get(vin, {})
                source_cents = arb.get("source_asking_cents") or 0
                opt_cents = arb.get("proposed_retail_cents") or ((inv.get("display_price") or 0) * 100)
                spread_cents = arb.get("modeled_gross_spread_cents") or max(0, opt_cents - source_cents)
                packets.append({
                    "order_id": r["id"],
                    "vin": vin,
                    "order_state": r["state"],
                    "buyer_name": cust.get("name", ""),
                    "buyer_email": cust.get("email", ""),
                    "buyer_phone": cust.get("phone", ""),
                    "buyer_zip": cust.get("zip", ""),
                    "created_at": r["created_at"],
                    "vehicle": f"{inv.get('year', '')} Tesla {inv.get('model', '')} {inv.get('trim', '')}".strip(),
                    "source_dealer": arb.get("source_dealer") or "",
                    "source_dealer_price": round(source_cents / 100) if source_cents else None,
                    "volts_retail_price": round(opt_cents / 100) if opt_cents else inv.get("display_price"),
                    "buyer_savings_badge": inv.get("savings_amount", 0),
                    "volts_upfront_spread": round(spread_cents / 100) if spread_cents else None,
                    "volts_4layer_profit_est": (round(spread_cents / 100) + 2000) if spread_cents else None,
                    "source_url": arb.get("source_url") or "",
                })
    packets_out.parent.mkdir(parents=True, exist_ok=True)
    packets_out.write_text(json.dumps({"updated_at": _utc_now(), "packets": packets}, indent=2))
    result = {
        "ok": True,
        "orders_scanned": len(packets),
        "matched_with_arbitrage": sum(1 for p in packets if p.get("volts_upfront_spread")),
    }
    _write_job_status(status_file, "5_match_customer_orders", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Volts & VINs automated pipeline jobs.")
    parser.add_argument(
        "--job",
        choices=["discover", "enrich", "build", "publish", "match", "all"],
        default="all",
    )
    parser.add_argument("--git-push", action="store_true")
    parser.add_argument("--status-file", type=Path, default=ROOT / ".data/jobs_status.json")
    args = parser.parse_args()

    summary = {}
    if args.job in ("discover", "all"):
        summary["discover"] = job_discover_vehicles(status_file=args.status_file)
    if args.job in ("enrich", "all"):
        summary["enrich"] = job_enrich_media(status_file=args.status_file)
    if args.job in ("build", "all"):
        summary["build"] = job_reprice_and_build(status_file=args.status_file)
    if args.job in ("publish", "all"):
        summary["publish"] = job_publish_and_index(git_push=args.git_push, status_file=args.status_file)
    if args.job in ("match", "all"):
        summary["match"] = job_match_customer_orders(status_file=args.status_file)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
