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
            if z == "20878" and label == "desktop":
                page.screenshot(path=f"{SHOTS}/results-20878-split-desktop.png", full_page=True)
            if z == "78701" and label == "desktop":
                page.screenshot(path=f"{SHOTS}/results-78701-redistricted-desktop.png", full_page=True)
        ctx.close()
    b.close()
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
