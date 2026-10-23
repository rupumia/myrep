"""End-to-end test of the built static site in headless Chromium.
Usage: python scripts/e2e_test.py [base_url]   (default http://localhost:8080)
Checks each ZIP renders, has no console errors / failed requests, and saves screenshots.
"""
import os, sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"
SHOTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "screenshots")
CASES = [  # zip, expected House district labels (current map), expect split notice, expect redistricting notice
    ("10001", ["NY-12"], False, False),
    ("94103", ["CA-11"], False, True),
    ("78701", ["TX-37"], False, True),
    ("20878", ["MD-08", "MD-06"], True, False),
    ("82001", ["WY-00"], False, False),
    ("05401", ["VT-00"], False, False),
    ("20001", ["DC-00"], False, False),
    ("53066", ["WI-05"], False, False),  # verified with Census geocoder (119th and 120th): WI-05
    ("00000", [], False, False),
]
fails = []
exe = os.environ.get("CHROME", "/usr/bin/google-chrome")
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=exe if os.path.exists(exe) else None)
    for label, vp in (("desktop", {"width": 1280, "height": 900}), ("mobile", {"width": 390, "height": 844})):
        ctx = b.new_context(viewport=vp, device_scale_factor=2 if label == "mobile" else 1)
        page = ctx.new_page(); errors = []
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("requestfailed", lambda r: errors.append(f"failed {r.url}"))
        page.goto(BASE + "/", wait_until="networkidle")
        if label == "desktop" or True:
            page.screenshot(path=f"{SHOTS}/home-{label}.png", full_page=False)
        for z, dists, split, redrawn in CASES:
            errors.clear()
            page.fill("#zip", z); page.click("button[type=submit]")
            page.wait_for_function("() => !document.querySelector('#results .skeleton')", timeout=15000)
            page.wait_for_load_state("networkidle")
            txt = page.inner_text("#results")
            ok = True
            if z == "00000":
                ok = "couldn't find" in txt
            else:
                cards = page.locator("article.card").count()
                exp_cards = (0 if z == "20001" else 2) + len(dists)
                if cards != exp_cards: ok = False; print(z, "cards", cards, "expected", exp_cards)
                if split != ("split across" in txt.lower()): ok = False; print(z, "split notice mismatch")
                if redrawn != ("redrew its congressional map" in txt): ok = False; print(z, "redistricting notice mismatch")
                if "running in 2026" not in txt.lower(): ok = False
                # a member card must show at least one vote badge
                if page.locator(".badge").count() == 0: ok = False; print(z, "no vote badges")
                if z == "53066" and "Wisconsin · 5th District" not in page.inner_text(".loc"): ok = False; print(z, "district label mismatch")
                # AIPAC-related flags: separate labels, 2025-26 only, never styled like vote badges
                for t in page.locator("#results .flag").all_inner_texts():
                    if "(2025-26)" not in t or "2023" in t: ok = False; print(z, "bad flag text", t)
                if page.locator(".flag.badge, .flag.v-yea, .flag.v-nay").count(): ok = False; print(z, "flag styled as vote")
                if page.locator(".flag-aipac.flag-udp").count(): ok = False; print(z, "combined flag")
                fin_cards = page.locator("article.card [data-panel=money]").count()
                heads = page.locator("article.card [data-panel=money] h4", has_text="AIPAC-related money").count()
                if heads != fin_cards: ok = False; print(z, "AIPAC detail missing", heads, fin_cards)
                dheads = page.locator("article.card [data-panel=money] h4", has_text="Weapons-industry PAC money").count()
                if dheads != fin_cards: ok = False; print(z, "weapons-industry detail missing", dheads, fin_cards)
                if page.locator(".flag-def.flag-aipac, .flag-def.flag-udp").count(): ok = False; print(z, "weapons flag combined with AIPAC flag")
                if z == "53066" and page.locator("article.card .flag-def").count() < 2: ok = False; print(z, "expected weapons-industry flags (Baldwin, Fitzgerald)")
                # Israel-related votes: listed before every other vote on each card, visible, labeled with a neutral pill
                order = page.evaluate("""() => [...document.querySelectorAll('article.card')].map(c => ({
                    name: (c.querySelector('h3')?.firstChild?.textContent || '').trim(),
                    seq: [...c.querySelectorAll('ul.votes > li')].map(li => li.classList.contains('isr') ? 1 : 0),
                    hiddenIsr: c.querySelectorAll('ul.votes > li.isr[hidden]').length,
                    pills: c.querySelectorAll('ul.votes > li.isr .topic-isr').length,
                    dates: [...c.querySelectorAll('ul.votes > li.isr .small')].map(e => e.textContent.split(' · ')[0])}))""")
                for c in order:
                    n = sum(c["seq"])
                    if c["seq"][:n] != [1] * n: ok = False; print(z, c["name"], "Israel-related votes not first", c["seq"][:12])
                    if c["hiddenIsr"]: ok = False; print(z, c["name"], "Israel-related votes hidden behind 'Show all'")
                    if c["pills"] != n: ok = False; print(z, c["name"], "missing Israel-related pill", c["pills"], n)
                    ds = [d for d in c["dates"]]
                    import datetime as _dt
                    pd = [_dt.datetime.strptime(d.strip(), "%b %d, %Y") for d in ds]
                    if pd != sorted(pd, reverse=True): ok = False; print(z, c["name"], "Israel-related votes not newest-first")
                    if z == "53066" and label == "desktop": print(f"  {c['name']}: {n} Israel-related vote(s) listed first of {len(c['seq'])}")
                if page.locator(".topic-isr.badge, .topic-isr.v-yea, .topic-isr.v-nay").count(): ok = False; print(z, "Israel pill styled as vote")
            # photos 404 are tolerated by design (hidden), but count them
            real_errors = [e for e in errors if "images/congress" not in e]
            if real_errors: ok = False; print(z, label, "errors:", real_errors[:5])
            print(f"[{label}] {z}: {'PASS' if ok else 'FAIL'}")
            if not ok: fails.append((label, z))
            if z == "10001":
                page.screenshot(path=f"{SHOTS}/results-10001-{label}.png", full_page=True)
                # open the money tab on the first card and a race detail
                page.locator("[data-tab=money]").first.click()
                page.locator("details.cand summary").first.click()
                page.screenshot(path=f"{SHOTS}/results-10001-money-{label}.png", full_page=True)
            if z == "53066":
                page.screenshot(path=f"{SHOTS}/results-53066-{label}.png", full_page=True)
                card = page.locator("article.card", has=page.locator("li.isr")).first
                if label == "mobile" and card.count():
                    card.locator("ul.votes").scroll_into_view_if_needed()
                    card.screenshot(path=os.environ.get("ISRAEL_SHOT", f"{SHOTS}/results-53066-israel-mobile.png"))
            if z == "20878" and label == "desktop":
                page.screenshot(path=f"{SHOTS}/results-20878-split-desktop.png", full_page=True)
            if z == "78701" and label == "desktop":
                page.screenshot(path=f"{SHOTS}/results-78701-redistricted-desktop.png", full_page=True)
        ctx.close()
    b.close()
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
