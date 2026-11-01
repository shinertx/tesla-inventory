#!/usr/bin/env python3
"""Rank private asking-price spread scenarios; no collected-profit or income claims."""
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
    catalog_root: Path | None = None,
) -> list[dict]:
    root = Path(catalog_root or ROOT)
    public = json.loads((root / 'inventory.json').read_text())['items']
    opportunities = json.loads((root / '.data/arbitrage_opportunities.json').read_text())['items']
    published = {item['vin']: item for item in public}
    deals = []
    for source in opportunities:
        vehicle = published.get(source['vin'])
        if not vehicle or (models and vehicle['model'] not in models):
            continue
        source_ask = source['source_asking_cents'] / 100
        published_price = vehicle['display_price']
        proposed_price = source['proposed_retail_cents'] / 100
        reference = (source.get('reference_cents') or 0) / 100
        scenario_price = published_price if only_live_marked_up else proposed_price
        spread = round(scenario_price - source_ask, 2)
        if spread < min_spread_dollars:
            continue
        deals.append({
            'vin': source['vin'], 'year': vehicle['year'], 'model': vehicle['model'],
            'trim': vehicle['trim'], 'mileage': vehicle['mileage'],
            'state': vehicle.get('state') or 'US',
            'source_dealer': source.get('source_dealer') or 'Source dealer not recorded',
            'source_url': source.get('source_url') or '',
            'source_ask_dollars': source_ask, 'live_price_dollars': published_price,
            'proposed_dollars': proposed_price, 'ref_dollars': reference,
            'buyer_savings_dollars': max(0, round(reference - scenario_price, 2)),
            'modeled_gross_spread_dollars': spread,
            'spread_basis': 'published_price_minus_source_ask' if only_live_marked_up else 'proposed_price_minus_source_ask',
            'review_flags': source.get('review_flags') or [],
        })
    deals.sort(key=lambda deal: (deal['modeled_gross_spread_dollars'], -deal['live_price_dollars']), reverse=True)
    return deals[:limit]


def write_markdown_report(output_path: Path | None = None, min_spread_dollars: int = 4000, *, catalog_root: Path | None = None) -> dict:
    root = Path(catalog_root or ROOT)
    private_root = (root / '.data').resolve()
    output = Path(output_path or private_root / 'top-arbitrage-deals.md').resolve()
    if not output.is_relative_to(private_root):
        raise ValueError('Private deal reports must remain under .data; public output is refused')
    all_deals = load_top_deals(min_spread_dollars=min_spread_dollars, limit=25, catalog_root=root)
    volume = load_top_deals(min_spread_dollars=min_spread_dollars, models=('Model 3', 'Model Y'), limit=25, catalog_root=root)
    lines = [
        '# Private Tesla asking-price spread scenarios', '',
        f'Minimum modeled gross spread: ${min_spread_dollars:,.2f}. No upper spread cap.', '',
        'Private operator report. Do not publish supplier identities, asking prices, or source links.',
        'Modeled gross spread = published estimated vehicle price minus recorded source asking price, before all costs.',
        'These are asking-price scenarios, not collected revenue, net profit, or completed-sale values.',
        'No negotiation discount, lender reserve, or shipping income is assumed.',
        'Source asking prices may be stale, conditional, or include unavailable incentives.',
        'Availability, seller hold, exact equipment, condition, title, and fees require authentic evidence before a payable quote.',
        'Reference comparisons use peer asking prices; they do not prove realized buyer savings.', '',
    ]
    for title, deals in [('Model 3 and Model Y', volume), ('All models', all_deals)]:
        lines.extend([
            '## ' + title, '',
            '| VIN | Vehicle | Miles | State | Source asking price | Published estimate | Peer asking reference | Difference vs reference | Modeled gross spread before costs | Source link |',
            '|---|---|---:|---|---:|---:|---:|---:|---:|---|',
        ])
        for deal in deals:
            link = f"[Listing]({deal['source_url']})" if deal['source_url'] else 'Not recorded'
            lines.append(
                f"| `{deal['vin']}` | {deal['year']} {deal['model']} {deal['trim']} | {deal['mileage']:,} | {deal['state']} "
                f"| ${deal['source_ask_dollars']:,.2f} | ${deal['live_price_dollars']:,.2f} | ${deal['ref_dollars']:,.2f} "
                f"| ${deal['buyer_savings_dollars']:,.2f} | ${deal['modeled_gross_spread_dollars']:,.2f} | {link} |"
            )
        lines.append('')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text('\n'.join(lines))
    output.chmod(0o600)
    return {'all_count': len(all_deals), 'm3_my_count': len(volume)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--min-spread', type=int, default=4000, help='Minimum modeled gross spread before costs, in dollars')
    parser.add_argument('--out', type=Path, default=None, help='Private report path under .data (default: .data/top-arbitrage-deals.md)')
    args = parser.parse_args()
    stats = write_markdown_report(args.out, min_spread_dollars=args.min_spread)
    print(f"Private report written (Model 3/Y: {stats['m3_my_count']}, all models: {stats['all_count']}).")


if __name__ == '__main__':
    main()
