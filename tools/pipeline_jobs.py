#!/usr/bin/env python3
"""Real-time & scheduled pipeline jobs for Volts & VINs.

Breaks the marketplace lifecycle into 5 discrete, auditable jobs:
1. discover_vehicles   — Pulls fresh Tesla VIN observations from live sources (Autolist, CarGurus, TrueCar, Carvana).
2. enrich_media        — Backfills VIN-bound multi-photo galleries for newly discovered vehicles.
3. reprice_and_build   — Recomputes peer benchmarks, dynamic 50/50 buyer-seller savings, Top Arbitrage Deals, and 197 HTML/AI pages.
4. publish_and_index   — Pushes updated catalog to GitHub Pages (voltsandvins.com) and submits eligible URLs to IndexNow.
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
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.collect import source_url, parse_source
from tools.inventory import ingest, export
from tools.build import build as build_catalog
from tools.top_arbitrage_deals import load_top_deals, write_markdown_report
from tools.indexnow import ping_indexnow, load_sitemap_urls
from app.catalog import stock_id_for, VIN_PATTERN
from tools.public_site import public_files, is_public_artifact, VIN_RE


CARGURUS_REGIONAL_HUBS = (
    "90001", "94102", "98101", "85001", "80202", "75201", "77002",
    "60601", "55401", "64106", "30303", "33101", "28202", "20001",
    "10001", "02108", "44101", "96813", "99501",
)

DEFAULT_PARTITIONS = (
    [("carmax", "All", 0, 22)]
    + [(f"cargurus_hub:{z}", m, 0, 21) for z in CARGURUS_REGIONAL_HUBS for m in ("Model Y", "Model 3", "Model S", "Model X", "Cybertruck")]
    + [("cargurus", "Cybertruck", yr, 21) for yr in range(2026, 2023, -1)]
    + [("cargurus", "Model Y", yr, 21) for yr in range(2026, 2019, -1)]
    + [("cargurus", "Model 3", yr, 21) for yr in range(2026, 2016, -1)]
    + [("cargurus", "Model X", yr, 21) for yr in range(2026, 2015, -1)]
    + [("cargurus", "Model S", yr, 21) for yr in range(2026, 2012, -1)]
)


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

    mc_key = (os.getenv("MARKETCHECK_API_KEY") or "").strip()
    if partitions is None:
        partitions = list(DEFAULT_PARTITIONS)
        if mc_key:
            partitions = [("marketcheck", m, 0, 20) for m in ("Model Y", "Model 3", "Model S", "Model X", "Cybertruck")] + partitions
    now = _utc_now()
    accepted_total = 0
    partition_results = []
    blocked_hosts = set()
    carmax_session = None
    for raw_source, model, year, pages in partitions:
        hub_zip = None
        source = raw_source
        if raw_source.startswith("cargurus_hub:"):
            source = "cargurus"
            hub_zip = raw_source.split(":", 1)[1]
        seen_vins: set[str] = set()
        sort_passes = [("PRICE", "ASC"), ("PRICE", "DESC"), ("DEAL_SCORE", "ASC")] if (source == "cargurus" and pages >= 20) else [("PRICE", "ASC")]
        for sort_type, sort_dir in sort_passes:
            exhausted = False
            for page in range(1, pages + 1):
                if hub_zip:
                    url = source_url(source, model, year, page, zip_code=hub_zip, distance=500, sort_type=sort_type, sort_dir=sort_dir)
                elif (sort_type, sort_dir) != ("PRICE", "ASC"):
                    url = source_url(source, model, year, page, sort_type=sort_type, sort_dir=sort_dir)
                else:
                    url = source_url(source, model, year, page)
                host = urlsplit(url).hostname
                if host in blocked_hosts:
                    exhausted = True
                    break
                try:
                    if source == "carmax":
                        if carmax_session is None:
                            carmax_session = requests.Session(impersonate="chrome120")
                            carmax_session.get("https://www.carmax.com/cars/tesla", timeout=15)
                        resp = carmax_session.get(
                            url,
                            headers={"Referer": "https://www.carmax.com/cars/tesla", "Accept": "application/json"},
                            timeout=15,
                        )
                    else:
                        resp = requests.get(url, impersonate="chrome120", timeout=15)
                    if resp.status_code != 200:
                        if resp.status_code in (403, 429):
                            blocked_hosts.add(host)
                        partition_results.append({
                            "source": source,
                            "model": model,
                            "year": year,
                            "page": page,
                            "ok": False,
                            "status_code": resp.status_code,
                        })
                        exhausted = True
                        break
                    raw_json = resp.json() if source == "cargurus" and hasattr(resp, "json") else None
                    if source == "cargurus" and raw_json is None:
                        if page == 1:
                            exhausted = True
                        break
                    rows = parse_source(source, resp, model, year)
                    valid_rows = [
                        r for r in rows
                        if r.get("source_url")
                        and r["source_url"].rstrip("/") not in ("https://www.autolist.com", "https://www.truecar.com")
                    ]
                    fresh_rows = [r for r in valid_rows if r.get("vin") not in seen_vins]
                    for r in valid_rows:
                        if r.get("vin"):
                            seen_vins.add(r["vin"])
                    if fresh_rows:
                        accepted = ingest(db_path, fresh_rows, source, _utc_now(), complete=False)
                        accepted_total += accepted
                        partition_results.append({
                            "source": source,
                            "model": model,
                            "year": year,
                            "page": page,
                            "ok": True,
                            "fetched": len(fresh_rows),
                            "accepted": accepted,
                        })
                    if source == "cargurus":
                        if isinstance(raw_json, list) and len(raw_json) < 48 or not rows:
                            exhausted = True
                            break
                        if not fresh_rows:
                            break
                    if source in ("truecar", "carmax", "marketcheck") and not fresh_rows:
                        exhausted = True
                        break
                except Exception as exc:
                    partition_results.append({
                        "source": source,
                        "model": model,
                        "year": year,
                        "page": page,
                        "ok": False,
                        "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                    })
                    exhausted = True
                    break
            if exhausted:
                break
    if accepted_total > 0 and db_path.exists():
        export(db_path, snapshot_path)
    result = {
        "ok": True,
        "accepted_observations": accepted_total,
        "partitions_checked": len(partition_results),
        "partitions_succeeded": sum(1 for p in partition_results if p.get("ok")),
        "marketcheck_configured": bool(mc_key),
        "details": partition_results,
    }
    _write_job_status(status_file, "1_discover_vehicles", result)
    return result


def job_enrich_media(
    *,
    snapshot_path: Path = ROOT / ".data/source_snapshot.json",
    gallery_path: Path = ROOT / ".data/vehicle_photos.json",
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
    if any(isinstance(row,dict) and row.get('stock_id') and not row.get('vin') for row in rows):
        res={"ok":False,"reason":"private_vin_source_required"}
        _write_job_status(status_file,"2_enrich_media",res)
        return res
    galleries = _private_gallery_cache(gallery_path)
    added = 0
    updated = 0
    multi = 0
    for row in rows:
        vin = row.get("vin", "")
        if not vin:
            continue
        existing = galleries.get(vin, [])
        merged = normalize_photos(existing + row.get("photos", []))
        if not merged and row.get("photo_url"):
            merged = normalize_photos([row["photo_url"]])
        if merged and merged!=existing:
            updated+=int(vin in galleries)
            added+=int(vin not in galleries)
            galleries[vin] = merged
        if len(galleries.get(vin, [])) > 1:
            multi += 1
    if added > 0 or updated > 0 or (galleries and not gallery_path.exists()):
        gallery_path.parent.mkdir(parents=True, exist_ok=True,mode=0o700)
        gallery_path.write_text(json.dumps(galleries, separators=(",", ":")))
        gallery_path.chmod(0o600)
    result = {
        "ok": True,
        "catalog_vins_checked": len(rows),
        "galleries_total": len(galleries),
        "multi_photo_vins": multi,
        "new_galleries_indexed": added,
        "existing_galleries_updated": updated,
    }
    _write_job_status(status_file, "2_enrich_media", result)
    return result


def _private_gallery_cache(gallery_path: Path) -> dict:
    """Seed future media jobs from original private arrays, never proxy/public shards."""
    from tools.media import normalize_photos
    galleries=json.loads(gallery_path.read_text()) if gallery_path.exists() else {}
    if not isinstance(galleries,dict) or any(not VIN_PATTERN.fullmatch(str(vin)) for vin in galleries):
        raise ValueError('Private gallery cache requires complete VIN identities')
    transaction_path=gallery_path.parent/'transaction_inventory.json'
    if transaction_path.exists():
        for row in json.loads(transaction_path.read_text()).get('items',[]):
            vin=row.get('vin')
            if not VIN_PATTERN.fullmatch(str(vin)):
                raise ValueError('Private transaction inventory requires complete VIN identities')
            photos=normalize_photos((galleries.get(vin) or [])+(row.get('photos') or []))
            if photos:galleries[vin]=photos
    return galleries


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
    # Fresh CI runners have no private baseline. Refuse a partial/empty scrape before it can replace the storefront.
    try:
        source_rows = json.loads(snapshot_path.read_text()).get("items", [])
        source_count = len({row.get("vin") for row in source_rows if isinstance(row, dict) and row.get("vin")})
        existing_path = output_dir / "inventory.json"
        existing_items=json.loads(existing_path.read_text()).get("items", []) if existing_path.exists() else []
        existing_count = len(existing_items)
    except (OSError, ValueError, AttributeError, TypeError):
        source_count, existing_count,existing_items = 0, 0,[]
    if not source_count or source_count < existing_count * .8:
        result = {"ok": False, "reason": "source_coverage_requires_review", "source_vins": source_count,
                  "existing_catalog_vins": existing_count, "published_unchanged": True}
        _write_job_status(status_file, "3_reprice_and_build", result)
        return result
    if any(row.get('stock_id') and not row.get('vin') for row in existing_items) and not (output_dir/'.data/transaction_inventory.json').exists():
        result={"ok":False,"reason":"private_transaction_inventory_required","published_unchanged":True}
        _write_job_status(status_file,"3_reprice_and_build",result)
        return result
    gallery_path=output_dir/'.data/vehicle_photos.json'
    galleries=_private_gallery_cache(gallery_path)
    gallery_path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    gallery_path.write_text(json.dumps(galleries,separators=(',',':')));gallery_path.chmod(0o600)
    manifest = build_catalog(source=snapshot_path, output=output_dir,gallery_source=gallery_path)
    docs_out = output_dir / ".data/top-arbitrage-deals.md"
    write_markdown_report(docs_out, min_spread_dollars=min_spread_dollars, catalog_root=output_dir)
    deals = load_top_deals(min_spread_dollars=min_spread_dollars, limit=1000, catalog_root=output_dir)
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
    """Job 4: Optionally commit/push updated static catalog and submit deployed URLs to IndexNow; acceptance does not prove indexing."""
    indexnow_res = {}
    git_res = {"pushed": False}
    if git_push:
        try:
            public_artifacts={path.relative_to(repo_dir.resolve()).as_posix() for path in public_files(repo_dir)}
            status = subprocess.run(
                ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames"],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            if status.returncode:raise ValueError('Public git status is unavailable')
            selected=[]
            records=status.stdout.split('\0') if '\0' in status.stdout else status.stdout.splitlines()
            for record in records:
                if len(record)<4:continue
                code,path=record[:2],record[3:]
                if path in public_artifacts or ('D' in code and is_public_artifact(path) and not (repo_dir/path).exists()):
                    selected.append(path)
            if selected:
                # NUL pathspecs avoid argument limits. Literal matching cannot stage nearby private paths.
                with tempfile.NamedTemporaryFile() as pathspec:
                    pathspec.write(b''.join(path.encode()+b'\0' for path in sorted(set(selected))));pathspec.flush()
                    scope=['--pathspec-from-file='+pathspec.name,'--pathspec-file-nul']
                    env={**os.environ,'GIT_LITERAL_PATHSPECS':'1'}
                    subprocess.run(["git","add",*scope],cwd=repo_dir,check=True,env=env)
                    subprocess.run(["git","commit","--only","-m",f"Automated catalog & dynamic pricing refresh ({_utc_now()[:16]}Z)",*scope],
                                   cwd=repo_dir,check=True,env=env)
                subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=repo_dir, check=True)
                git_res = {"pushed": True}
            else:
                git_res = {"pushed": False, "reason": "no_catalog_changes"}
        except Exception as exc:
            git_res = {"pushed": False, "error": str(exc)[:200]}
    if ping_search_engines:
        sitemap = repo_dir / "sitemap.xml"
        release = repo_dir / "search-release.json"
        if not sitemap.exists():
            indexnow_res = {"deferred": True, "reason": "local_sitemap_missing"}
        elif not release.exists():
            indexnow_res = {"deferred": True, "reason": "local_release_manifest_missing"}
        elif git_res.get("error"):
            indexnow_res = {"deferred": True, "reason": "git_publish_failed"}
        else:
            # Two bounded reads; a successful push or equal sitemap alone is not deployment.
            try:
                with urllib.request.urlopen("https://voltsandvins.com/sitemap.xml", timeout=10) as response:
                    public_sitemap = response.read(10_000_001)
                with urllib.request.urlopen("https://voltsandvins.com/search-release.json", timeout=10) as response:
                    public_release = response.read(10_000_001)
                if public_release != release.read_bytes():
                    indexnow_res = {"deferred": True, "reason": "public_release_manifest_not_deployed"}
                elif public_sitemap != sitemap.read_bytes():
                    indexnow_res = {"deferred": True, "reason": "public_sitemap_not_deployed"}
                else:
                    urls=load_sitemap_urls(sitemap)
                    indexnow_res=({"deferred":True,"reason":"public_vin_urls_require_migration"}
                                  if any(VIN_RE.search(url) for url in urls) else ping_indexnow(urls=urls))
            except Exception as exc:
                partial = getattr(exc, "result", None)
                indexnow_res = {**partial, "error": str(exc)[:160]} if isinstance(partial, dict) else {
                    "deferred": True, "reason": "public_release_check_failed", "error": str(exc)[:160]}
    result = {
        "ok": True,
        "indexnow": indexnow_res,
        "git": git_res,
    }
    _write_job_status(status_file, "4_publish_and_index", result)
    return result


def send_deal_alert_email(
    packet: dict,
    *,
    to_email: str = os.getenv("ALERT_EMAIL_TO", "ben@jockeyvc.com"),
    from_email: str = os.getenv("ALERT_EMAIL_FROM", "deals@use-flows.com"),
    sendgrid_key: str | None = None,
) -> bool:
    """Send an instant dealer-arbitrage alert email via SendGrid v3 API when a customer requests a VIN."""
    api_key = (sendgrid_key if sendgrid_key is not None else os.getenv("SENDGRID_API_KEY", "")).strip()
    if not api_key:
        return False
    vin = packet.get("vin", "")
    vehicle = packet.get("vehicle") or f"Tesla ({vin})"
    spread = packet.get("modeled_gross_spread_dollars")
    spread_label = f"{'-' if spread < 0 else '+'}${abs(spread):,}" if spread is not None else None
    src_price = packet.get("source_dealer_price")
    vv_price = packet.get("volts_retail_price")
    savings = packet.get("buyer_savings_badge") or 0
    src_url = packet.get("source_url") or "https://voltsandvins.com/?vin=" + vin
    subject = (
        f"[Volts & VINs Deal Alert] {vehicle} ({vin}) — Modeled spread {spread_label} before costs"
        if spread is not None
        else f"[Volts & VINs Order Request] {vehicle} ({vin})"
    )
    lines = [
        "Customer vehicle request on Volts & VINs",
        "=================================================",
        f"Order ID: {packet.get('order_id')}",
        f"Buyer: {packet.get('buyer_name')} | {packet.get('buyer_email')} | {packet.get('buyer_phone')} | ZIP {packet.get('buyer_zip')}",
        "",
        f"Vehicle: {vehicle}",
        f"VIN: {vin}",
        f"Volts & VINs URL: https://voltsandvins.com/?vin={vin}",
        "",
        "Arbitrage & Source Dealer Breakdown:",
        f"- Source Dealer: {packet.get('source_dealer') or 'See source link'}",
    ]
    if src_price:
        lines.append(f"- Source Dealer Ask: ${src_price:,}")
    if vv_price:
        lines.append(f"- Volts & VINs Retail Price: ${vv_price:,} (Buyer Badge: Save ${savings:,})")
    if spread is not None:
        lines.append(f"- Modeled gross spread: {spread_label} before costs")
    lines.append("Asking-price projection only. No negotiated discount, lender income, or transport profit is assumed.")
    lines.append("Collected platform revenue is not established by this request or price gap.")
    lines.append(f"- Direct Source Listing Link: {src_url}")
    text_body = "\n".join(lines) + "\n"

    payload = json.dumps({
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": from_email, "name": "Volts & VINs Deal Desk"},
        "reply_to": {"email": to_email, "name": "Volts & VINs Deal Desk"},
        "subject": subject,
        "content": [{"type": "text/plain", "value": text_body}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def job_match_customer_orders(
    *,
    orders_db: Path = Path(os.getenv("ORDERS_DB", str(ROOT / ".data/orders.db"))),
    arb_path: Path = ROOT / ".data/arbitrage_opportunities.json",
    inv_path: Path = ROOT / ".data/transaction_inventory.json",
    packets_out: Path = ROOT / ".data/deal_packets.json",
    status_file: Path = ROOT / ".data/jobs_status.json",
    alert_email: str = os.getenv("ALERT_EMAIL_TO", "ben@jockeyvc.com"),
) -> dict:
    """Job 5: Real-time (60s) matcher pairing customer VIN reservation requests with private source dealer links & spreads."""
    if not orders_db.exists():
        res = {"ok": True, "orders_scanned": 0, "matched_packets": 0, "emails_sent": 0}
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
    inv_by_stock = {}
    if inv_path.exists():
        try:
            for item in json.loads(inv_path.read_text()).get("items", []):
                if item.get("vin"):
                    inv_by_vin[item["vin"]] = item
        except Exception:
            pass
    published_path=inv_path.parent.parent/'inventory.json' if inv_path.parent.name=='.data' else inv_path
    published_available=published_path.exists()
    published_by_vin={}
    if published_available:
        try:
            for item in json.loads(published_path.read_text()).get('items',[]):
                if item.get('stock_id'):inv_by_stock[item['stock_id']]=item
                elif item.get('vin'):published_by_vin[item['vin']]=item
        except (OSError,ValueError,TypeError):pass

    packets = []
    emails_sent = 0
    with sqlite3.connect(orders_db) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE IF NOT EXISTS order_alerts_sent (order_id TEXT PRIMARY KEY, recipient TEXT NOT NULL, sent_at INTEGER NOT NULL)"
        )
        already_sent = {
            r[0] for r in conn.execute("SELECT order_id FROM order_alerts_sent").fetchall()
        }
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
                try:stock_id=stock_id_for(vin)
                except ValueError:stock_id=None
                inv = (inv_by_stock.get(stock_id) or published_by_vin.get(vin,{})
                       if published_available else inv_by_vin.get(vin,{}))
                source_cents = arb.get("source_asking_cents")
                source_cents = source_cents if type(source_cents) is int and source_cents > 0 else None
                published_price = inv.get("display_price")
                retail_cents = round(published_price * 100) if type(published_price) in (int, float) and published_price > 0 else None
                spread_cents = retail_cents - source_cents if retail_cents is not None and source_cents is not None else None
                packet = {
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
                    "volts_retail_price": round(retail_cents / 100) if retail_cents is not None else None,
                    "buyer_savings_badge": inv.get("savings_amount", 0),
                    "modeled_gross_spread_dollars": round(spread_cents / 100) if spread_cents is not None else None,
                    "spread_basis": "published_price_minus_source_ask" if spread_cents is not None else "unavailable",
                    "ancillary_income_assumed_dollars": 0,
                    "collected_revenue_established": False,
                    "source_url": arb.get("source_url") or "",
                }
                packets.append(packet)
                is_test_or_cancelled = (
                    r["state"] == "cancelled"
                    or "SITE TEST" in str(packet.get("buyer_name", "")).upper()
                    or str(packet.get("buyer_email", "")).endswith(".test")
                )
                if r["id"] not in already_sent and not is_test_or_cancelled:
                    if send_deal_alert_email(packet, to_email=alert_email):
                        conn.execute(
                            "INSERT OR IGNORE INTO order_alerts_sent (order_id, recipient, sent_at) VALUES (?, ?, ?)",
                            (r["id"], alert_email, int(time.time())),
                        )
                        conn.commit()
                        emails_sent += 1
    packets_out.parent.mkdir(parents=True, exist_ok=True)
    packets_out.write_text(json.dumps({"updated_at": _utc_now(), "packets": packets}, indent=2))
    packets_out.chmod(0o600)
    result = {
        "ok": True,
        "orders_scanned": len(packets),
        "matched_with_arbitrage": sum(1 for p in packets if (p.get("modeled_gross_spread_dollars") or 0) > 0),
        "alert_recipient": alert_email,
        "emails_sent_this_run": emails_sent,
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
        if not summary["build"].get("ok"):
            print(json.dumps(summary, indent=2))
            raise SystemExit(1)
    if args.job in ("publish", "all"):
        summary["publish"] = job_publish_and_index(git_push=args.git_push, status_file=args.status_file)
    if args.job in ("match", "all"):
        summary["match"] = job_match_customer_orders(status_file=args.status_file)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
