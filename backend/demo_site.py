"""A local, deterministic website used for demos and browser integration tests."""

from __future__ import annotations

import csv
import io
from html import escape

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse


router = APIRouter()

PRODUCTS = [
    ("Aurora Desk Lamp", "39.00", "Lighting"),
    ("Bramble Ceramic Mug", "16.50", "Kitchen"),
    ("Cinder Notebook", "12.00", "Stationery"),
    ("Drift Wireless Keyboard", "89.00", "Desk"),
    ("Ember Travel Flask", "28.00", "Outdoors"),
    ("Fern Linen Tote", "24.00", "Accessories"),
    ("Glacier Water Bottle", "22.00", "Outdoors"),
    ("Harbor Wool Throw", "74.00", "Home"),
    ("Indigo Desk Mat", "31.00", "Desk"),
    ("Juniper Plant Stand", "58.00", "Home"),
    ("Kite Mechanical Pencil", "9.50", "Stationery"),
    ("Lumen Reading Light", "44.00", "Lighting"),
    ("Meadow Glass Carafe", "42.00", "Kitchen"),
    ("Northstar Headphones", "129.00", "Audio"),
    ("Orbit Charging Dock", "65.00", "Desk"),
    ("Pebble Cable Organizer", "14.00", "Desk"),
    ("Quartz Serving Board", "46.00", "Kitchen"),
    ("River Stone Coasters", "18.00", "Home"),
]
PAGE_SIZE = 6


@router.get("/demo", response_class=HTMLResponse)
async def demo_home() -> RedirectResponse:
    return RedirectResponse("/demo/catalog")


@router.get("/demo/catalog", response_class=HTMLResponse)
async def catalog(search: str = Query(default=""), page: int = Query(default=1, ge=1, le=20)) -> str:
    normalized = search.strip().lower()
    filtered = [product for product in PRODUCTS if not normalized or normalized in product[0].lower() or normalized in product[2].lower()]
    total_pages = max(1, (len(filtered) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, total_pages)
    visible = filtered[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
    cards = "".join(
        f"""
        <article class="product-card" data-testid="product-card">
          <div class="product-art" aria-hidden="true">{escape(product[0][0])}</div>
          <div class="product-copy">
            <h2 data-testid="product-name">{escape(product[0])}</h2>
            <p class="product-category">{escape(product[2])}</p>
            <p data-testid="product-price">${escape(product[1])}</p>
            <a class="product-link" href="/demo/product/{(page - 1) * PAGE_SIZE + visible.index(product)}">View product</a>
          </div>
        </article>
        """
        for product in visible
    )
    next_link = ""
    if page < total_pages:
        next_link = f'<a class="next-link" href="/demo/catalog?search={escape(search)}&page={page + 1}" aria-label="Next">Next</a>'
    previous_link = ""
    if page > 1:
        previous_link = f'<a class="prev-link" href="/demo/catalog?search={escape(search)}&page={page - 1}" aria-label="Previous">Previous</a>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Northwind Catalog Demo</title>
<style>
body{{font-family:Inter,system-ui,sans-serif;margin:0;background:#f5f7fb;color:#172033}}main{{max-width:1050px;margin:0 auto;padding:48px 24px}}header{{display:flex;justify-content:space-between;gap:24px;align-items:end;margin-bottom:32px}}h1{{font-size:36px;margin:0 0 8px}}.muted{{color:#6d7890}}form{{display:flex;gap:8px;align-items:end}}label{{display:flex;flex-direction:column;gap:6px;font-size:13px;font-weight:700}}input{{border:1px solid #cbd3e1;border-radius:10px;padding:12px 14px;min-width:260px;font:inherit}}button,.download{{border:0;border-radius:10px;padding:12px 16px;background:#375cf5;color:white;font-weight:800;cursor:pointer;text-decoration:none}}.catalog{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}.product-card{{background:white;border:1px solid #e1e6ef;border-radius:18px;overflow:hidden;display:flex;min-height:155px}}.product-art{{background:#e9efff;color:#375cf5;font-size:48px;font-weight:900;display:grid;place-items:center;width:100px}}.product-copy{{padding:18px}}h2{{font-size:17px;margin:0 0 4px}}.product-category{{margin:0 0 16px;color:#6d7890;font-size:13px}}.product-copy p[data-testid=product-price]{{font-weight:900;margin:0 0 12px}}a{{color:#375cf5;font-weight:700}}.toolbar{{display:flex;justify-content:space-between;align-items:center;margin:24px 0}}.pager{{display:flex;gap:18px}}@media(max-width:800px){{.catalog{{grid-template-columns:1fr}}header{{display:block}}form{{margin-top:20px}}input{{min-width:0;width:100%}}}}
</style></head><body><main>
<header><div><p class="muted">LOCAL DEMO WEBSITE · NORTHWIND</p><h1>Product catalog</h1><p class="muted">A predictable site for testing search, pagination, extraction, and downloads.</p></div>
<form method="get" action="/demo/catalog"><label for="search">Search products<input id="search" name="search" value="{escape(search)}" placeholder="Try lamp or desk"></label><button type="submit">Search</button></form></header>
<div class="toolbar"><span class="muted">{len(filtered)} result(s) · page {page} of {total_pages}</span><a class="download" href="/demo/download.csv?search={escape(search)}" download="northwind-products.csv">Download CSV</a></div>
<section class="catalog" aria-label="Product results">{cards or '<p>No products matched your search.</p>'}</section>
<nav class="toolbar" aria-label="Pagination"><div class="pager">{previous_link}{next_link}</div><span class="muted">Results are intentionally paginated.</span></nav>
</main></body></html>"""


@router.get("/demo/product/{product_id}", response_class=HTMLResponse)
async def product(product_id: int) -> str:
    item = PRODUCTS[product_id % len(PRODUCTS)]
    return f"<html><body><main><a href='/demo/catalog'>Back to catalog</a><h1>{escape(item[0])}</h1><p>${escape(item[1])}</p><p>{escape(item[2])}</p></main></body></html>"


@router.get("/demo/download.csv")
async def download_csv(search: str = "") -> StreamingResponse:
    normalized = search.strip().lower()
    rows = [product for product in PRODUCTS if not normalized or normalized in product[0].lower() or normalized in product[2].lower()]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["name", "price", "category"])
    writer.writerows(rows)
    return StreamingResponse(
        iter([buffer.getvalue().encode("utf-8")]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="northwind-products.csv"'},
    )

