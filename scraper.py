#!/usr/bin/env python3
"""
scraper.py — ToolSynk Portfolio Scraper
"""

import os, re, sys
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════
DEVELOPER_PLAY_ID = "7955739039198639107"
USE_NUMERIC_ID    = True

PORTFOLIO_TITLE   = "ToolSynk"
PORTFOLIO_TAGLINE = "Productivity Tools That Just Work"
CONTACT_EMAIL     = "contact@toolsynk.com"
PLAY_STORE_URL    = f"https://play.google.com/store/apps/dev?id={DEVELOPER_PLAY_ID}"

FALLBACK_APPS: List[dict] = [
    {
        "title":       "PDF Reader",
        "url":         "https://play.google.com/store/apps/details?id=com.toolsynk.pdfreader",
        "icon":        "https://placehold.co/240x240/0c0c0f/f97316?text=PDF",
        "rating":      "4.5",
        "price":       "FREE",
        "category":    "Productivity",
        "description": "Fast, clean PDF viewer for Android.",
    },
]

# ══════════════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════
BASE_URL      = "https://play.google.com"
DEV_PAGE_URL  = f"{BASE_URL}/store/apps/dev?id={DEVELOPER_PLAY_ID}"
ICON_SUFFIX   = "=w240-h240-rw"
TEMPLATE_FILE = "template.html"
OUTPUT_FILE   = "index.html"
PLACEHOLDER   = "<!-- {{APPS_PLACEHOLDER}} -->"

HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_JUNK  = re.compile(r"^\s*(\$[\d.]+|€[\d.]+|free|install|rated|[\d,]+\+?|[\d.]+\s*stars?)\s*$", re.I)
_PRICE = re.compile(r"\s*\$[\d.]+\s*$")

# Category detection
_CAT_RULES = [
    (["pdf", "reader", "viewer", "scanner", "ocr", "document"],            "Productivity"),
    (["qr", "barcode", "scanner", "code"],                                 "Utility"),
    (["watch", "clock", "face", "samsung", "wear", "galaxy"],              "Watch Face"),
    (["game", "mine", "craft", "skin", "addon", "map", "puzzle", "run"],   "Game"),
    (["weather", "forecast", "rain", "temperature"],                       "Weather"),
    (["vpn", "secure", "password", "vault", "privacy"],                    "Security"),
    (["photo", "camera", "edit", "filter", "collage"],                     "Photo"),
    (["music", "audio", "player", "sound", "beat"],                        "Music"),
]

def detect_category(title: str, pkg: str) -> str:
    t = (title + " " + pkg).lower()
    for kws, cat in _CAT_RULES:
        if any(k in t for k in kws):
            return cat
    return "Tool"


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def clean_icon(raw: str) -> str:
    if not raw: return ""
    cleaned = re.sub(r"=[a-zA-Z]?\d+[-=].*$", "", raw.strip())
    cleaned = re.sub(r"=[a-zA-Z]\d+$", "", cleaned)
    return cleaned + ICON_SUFFIX

def extract_title(link_tag) -> str:
    label = link_tag.get("aria-label", "").strip()
    if label and len(label) < 120:
        return _PRICE.sub("", label).strip()
    candidates = []
    for el in link_tag.find_all(["span", "div"]):
        txt = el.get_text(separator=" ", strip=True)
        if 3 < len(txt) < 120 and not _JUNK.match(txt) and "\n" not in txt:
            candidates.append(txt)
    if candidates:
        filtered = [c for c in candidates if 4 <= len(c) <= 70]
        best = sorted(filtered or candidates, key=len)[0]
        return _PRICE.sub("", best).strip()
    return ""

def extract_icon(link_tag) -> str:
    for img in link_tag.find_all("img"):
        for attr in ("src", "data-src"):
            val = img.get(attr, "")
            if "googleusercontent" in val:
                return clean_icon(val)
    return ""

def extract_rating(element) -> Optional[str]:
    node = element
    for _ in range(7):
        if node is None: break
        hit = node.find(attrs={"aria-label": re.compile(r"Rated\s+\d", re.I)})
        if hit:
            m = re.search(r"(\d+\.?\d*)", hit.get("aria-label", ""))
            if m: return m.group(1)
        node = getattr(node, "parent", None)
    return None

def fetch_missing_icon(url: str) -> str:
    try:
        r = requests.get(url, headers=HEADERS, params={"hl": "en"}, timeout=12)
        soup = BeautifulSoup(r.text, "html.parser")
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if "play-lh.googleusercontent" in src:
                return clean_icon(src)
    except Exception:
        pass
    return ""

def fetch_app_description(url: str) -> str:
    """Grab short description from individual app page."""
    try:
        r = requests.get(url, headers=HEADERS, params={"hl": "en"}, timeout=12)
        soup = BeautifulSoup(r.text, "html.parser")
        # Look for meta description
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            desc = meta["content"].strip()
            # Trim to ~100 chars
            return desc[:110] + ("…" if len(desc) > 110 else "")
    except Exception:
        pass
    return ""


# ══════════════════════════════════════════════════════════════════════════════
#  SCRAPER
# ══════════════════════════════════════════════════════════════════════════════

def scrape_apps() -> Optional[List[dict]]:
    print(f"[scraper] Fetching: {DEV_PAGE_URL}")
    try:
        session = requests.Session()
        session.get(BASE_URL, headers=HEADERS, timeout=10)
        resp = session.get(DEV_PAGE_URL, headers=HEADERS, params={"hl": "en", "gl": "US"}, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[scraper] ✗ {e}"); return None

    print(f"[scraper]   HTTP {resp.status_code} — {len(resp.text):,} bytes")
    if "play.google.com" not in resp.url or len(resp.text) < 5000:
        print("[scraper] ✗ Blocked"); return None

    soup = BeautifulSoup(resp.text, "html.parser")
    apps: List[dict] = []
    seen: set = set()

    for link in soup.find_all("a", href=re.compile(r"/store/apps/details\?id=")):
        href = link.get("href", "")
        qs   = parse_qs(urlparse(href).query)
        pkg  = qs.get("id", [None])[0]
        if not pkg or pkg in seen: continue
        seen.add(pkg)

        title  = extract_title(link) or pkg.split(".")[-1].replace("_"," ").title()
        icon   = extract_icon(link)
        rating = extract_rating(link)
        raw    = link.get("aria-label", "")
        pm     = re.search(r"\$[\d.]+", raw)
        price  = pm.group(0) if pm else "FREE"

        apps.append({
            "title":       title,
            "url":         urljoin(BASE_URL, href),
            "icon":        icon,
            "rating":      rating,
            "price":       price,
            "category":    detect_category(title, pkg),
            "description": "",
        })

    if apps:
        print(f"[scraper] ✓ Found {len(apps)} app(s)")
        for app in apps:
            if not app["icon"]:
                print(f"[scraper]   Fetching icon: {app['title']}")
                app["icon"] = fetch_missing_icon(app["url"])
            if not app["description"]:
                print(f"[scraper]   Fetching description: {app['title']}")
                app["description"] = fetch_app_description(app["url"])
        return apps

    print("[scraper] ✗ No apps found"); return None


# ══════════════════════════════════════════════════════════════════════════════
#  CARD GENERATION
# ══════════════════════════════════════════════════════════════════════════════

CAT_COLORS = {
    "Productivity": ("#f97316", "rgba(249,115,22,0.12)", "rgba(249,115,22,0.25)"),
    "Utility":      ("#fb923c", "rgba(251,146,60,0.12)", "rgba(251,146,60,0.25)"),
    "Tool":         ("#f97316", "rgba(249,115,22,0.12)", "rgba(249,115,22,0.25)"),
    "Security":     ("#ef4444", "rgba(239,68,68,0.12)",  "rgba(239,68,68,0.25)"),
    "Weather":      ("#38bdf8", "rgba(56,189,248,0.12)", "rgba(56,189,248,0.25)"),
    "Photo":        ("#e879f9", "rgba(232,121,249,0.12)","rgba(232,121,249,0.25)"),
    "Music":        ("#a78bfa", "rgba(167,139,250,0.12)","rgba(167,139,250,0.25)"),
    "Watch Face":   ("#fbbf24", "rgba(251,191,36,0.12)", "rgba(251,191,36,0.25)"),
    "Game":         ("#4ade80", "rgba(74,222,128,0.12)", "rgba(74,222,128,0.25)"),
}

def _star():
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-3.5 h-3.5"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77 5.82 21.02 7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>'

def _ext():
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5 opacity-70"><path fill-rule="evenodd" d="M4.25 5.5a.75.75 0 00-.75.75v8.5c0 .414.336.75.75.75h8.5a.75.75 0 00.75-.75v-4a.75.75 0 011.5 0v4A2.25 2.25 0 0112.75 17h-8.5A2.25 2.25 0 012 14.75v-8.5A2.25 2.25 0 014.25 4h5a.75.75 0 010 1.5h-5zm6.75-3a.75.75 0 01.75-.75h3.5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0V3.56l-3.72 3.72a.75.75 0 11-1.06-1.06l3.72-3.72H11a.75.75 0 01-.75-.75z" clip-rule="evenodd"/></svg>'

def generate_card(app: dict) -> str:
    title    = app.get("title") or "App"
    url      = app.get("url") or "#"
    icon     = app.get("icon") or "https://placehold.co/80x80/0c0c0f/f97316?text=T"
    rating   = app.get("rating")
    price    = app.get("price", "FREE")
    category = app.get("category", "Tool")
    desc     = app.get("description", "")
    safe     = title.replace('"', '&quot;')
    letter   = title[0].upper() if title else "T"

    col, bg, bdr = CAT_COLORS.get(category, CAT_COLORS["Tool"])

    rating_html = ""
    if rating:
        try:
            rating_html = f"""
              <div class="flex items-center gap-1.5" style="color:#f97316;">
                {_star()}
                <span class="text-sm font-bold">{float(rating):.1f}</span>
                <span class="text-xs" style="color:#3f3f46;">/5</span>
              </div>"""
        except ValueError:
            pass

    desc_html = f'<p class="text-sm leading-relaxed line-clamp-2" style="color:#52525b;">{desc}</p>' if desc else ""

    is_free   = price.upper() == "FREE"
    price_col = "#4ade80" if is_free else "#f97316"
    price_bg  = "rgba(74,222,128,0.10)" if is_free else "rgba(249,115,22,0.10)"
    price_bdr = "rgba(74,222,128,0.25)" if is_free else "rgba(249,115,22,0.25)"

    return f"""
        <div class="card-item group relative flex flex-col sm:flex-row gap-6 rounded-2xl border p-6 transition-all duration-300 ease-out hover:border-orange-500/30 hover:shadow-[0_16px_64px_rgba(249,115,22,0.10)] hover:-translate-y-1" style="background:#0c0c0f;border-color:rgba(255,255,255,0.06);">

          <!-- Left glow bar -->
          <div class="absolute left-0 top-6 bottom-6 w-[2px] rounded-full transition-all duration-300 opacity-0 group-hover:opacity-100" style="background:linear-gradient(to bottom, transparent, {col}, transparent);"></div>

          <!-- Icon -->
          <div class="flex-shrink-0 flex flex-col items-center gap-3">
            <img
              src="{icon}"
              alt="{safe}"
              width="80" height="80"
              loading="lazy"
              class="w-20 h-20 rounded-2xl object-cover shadow-lg ring-1 ring-white/8 transition-transform duration-300 group-hover:scale-105"
              onerror="this.onerror=null;this.src='https://placehold.co/80x80/0c0c0f/f97316?text={letter}'"
            >
            <!-- Price pill -->
            <span class="text-[11px] font-bold tracking-widest px-3 py-1 rounded-full border"
              style="color:{price_col};background:{price_bg};border-color:{price_bdr};">{price}</span>
          </div>

          <!-- Info -->
          <div class="flex flex-col flex-1 gap-3 min-w-0">
            <!-- Title + category -->
            <div class="flex items-start justify-between gap-3 flex-wrap">
              <div>
                <h3 class="text-white font-bold text-xl leading-tight mb-1 group-hover:text-orange-50 transition-colors">{title}</h3>
                <span class="inline-block text-[11px] font-semibold tracking-wider px-2.5 py-0.5 rounded-md"
                  style="color:{col};background:{bg};border:1px solid {bdr};">{category}</span>
              </div>
              {rating_html}
            </div>

            {desc_html}

            <!-- CTA -->
            <div class="mt-auto pt-1">
              <a
                href="{url}"
                target="_blank"
                rel="noopener noreferrer"
                class="inline-flex items-center gap-2 rounded-xl px-5 py-2.5 text-sm font-semibold text-white transition-all duration-200 active:scale-95 hover:opacity-90"
                style="background:linear-gradient(135deg,#ea580c,#f97316);box-shadow:0 4px 20px rgba(249,115,22,0.25);"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-4 h-4"><path d="M3 22V2l19 10L3 22z"/></svg>
                Get it on Google Play
                {_ext()}
              </a>
            </div>
          </div>
        </div>"""


def build_cards(apps: List[dict]) -> str:
    if not apps:
        return '<p class="text-center py-20 text-sm" style="color:#3f3f46;">No apps found.</p>'
    return "\n".join(generate_card(app) for app in apps)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    apps   = scrape_apps()
    source = "live"
    if not apps:
        print("[scraper] ⚠ Using fallback")
        apps, source = FALLBACK_APPS, "fallback"

    print(f"[scraper] Building {len(apps)} app(s) from {source}")

    if not os.path.isfile(TEMPLATE_FILE):
        print(f"[scraper] ✗ {TEMPLATE_FILE} not found", file=sys.stderr); sys.exit(1)

    with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
        tpl = f.read()

    if PLACEHOLDER not in tpl:
        print(f"[scraper] ✗ Placeholder missing", file=sys.stderr); sys.exit(1)

    out = tpl
    out = out.replace("{{PORTFOLIO_TITLE}}",   PORTFOLIO_TITLE)
    out = out.replace("{{PORTFOLIO_TAGLINE}}", PORTFOLIO_TAGLINE)
    out = out.replace("{{DEVELOPER_PLAY_ID}}", DEVELOPER_PLAY_ID)
    out = out.replace("{{CONTACT_EMAIL}}",     CONTACT_EMAIL)
    out = out.replace("{{PLAY_STORE_URL}}",    PLAY_STORE_URL)

    ts = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")
    injection = (
        f"\n        <!-- AUTO-GENERATED | {ts} | {len(apps)} app(s) -->\n"
        + build_cards(apps)
        + "\n        <!-- /AUTO-GENERATED -->"
    )
    out = out.replace(PLACEHOLDER, injection)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(out)

    print(f"[scraper] ✓ {OUTPUT_FILE} written ({len(out):,} bytes, {len(apps)} card(s))")


if __name__ == "__main__":
    main()
