"""Fetchers for Nov 3, 2026 Wisconsin results (used by scripts/wi_results_refresh.py and wi_results.py).

Wisconsin has no statewide results feed (the Elections Commission says so), so each source is the publisher closest to
the count: county clerks' own results pages for county-level numbers, and AP vote data as published by NBC News for
statewide/congressional races. A third-party aggregator (Exa Library) fills in the races NBC does not carry; its numbers
for the races both publish (Governor, Attorney General, Secretary of State) match NBC's AP data exactly.
Nothing is estimated: every number below is copied from the page it was fetched from, with the page's own timestamp.
"""
import re, json, io, html as htmllib, datetime as dt, requests

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/124 Safari/537.36 myrep.info results check"}
def _get(url):
    r = requests.get(url, headers=UA, timeout=60); r.raise_for_status(); return r
def _num(s): return int(re.sub(r"[^\d]", "", s) or 0)
def _text(h):
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"(?s)<[^>]+>", "\n", h)
    h = htmllib.unescape(h).replace("\xa0", " ")
    return [l.strip() for l in h.split("\n") if l.strip()]
def now_utc(): return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ---------- Waukesha County: one ASP.NET page with every contest ----------
WAUKESHA_URL = "https://electionresults.waukeshacounty.gov/contests.aspx?contest=-1"
def waukesha():
    h = _get(WAUKESHA_URL).text
    status = re.search(r"(Unofficial Results[^<\n]{0,60})", h)
    out = {}
    for m in re.finditer(r'<div class="summaryCaption">\s*(.*?)\s*</div>(.*?)(?=<div class="summaryCaption">|\Z)', h, re.S):
        title, body = htmllib.unescape(m.group(1)).strip(), m.group(2)
        cands = []
        for r in re.finditer(r'class="lblCandName">(.*?)</span>.*?class="lblVotes">(.*?)</span>.*?class="lblPercent">(.*?)</span>', body, re.S):
            cands.append({"label": htmllib.unescape(r.group(1)).strip(), "votes": _num(r.group(2)), "pct": float(re.sub(r"[^\d.]", "", r.group(3)) or 0)})
        rep = re.search(r"(\d+)\s+of\s+(\d+)\s+Units reported", body)
        if cands: out[title] = {"candidates": cands, "reporting": [int(rep.group(1)), int(rep.group(2))] if rep else None}
    return {"name": "Waukesha County Clerk, unofficial results", "url": "https://electionresults.waukeshacounty.gov/contests.aspx?contest=-1",
            "as_of_note": status.group(1).strip() if status else "", "contests": out}

# ---------- Jefferson County: HTML cards, "AS OF 11-04-2026 11:58 am" ----------
JEFFERSON_URL = "https://apps.jeffersoncountywi.gov/jc/election/results/11032026"
def jefferson():
    L = _text(_get(JEFFERSON_URL).text)
    as_of = next((re.search(r"AS OF (.+)", l).group(1) for l in L if l.startswith("AS OF")), "")
    out, i = {}, 0
    while i < len(L):
        m = re.match(r"(.+?) Vote for 1$", L[i])
        if m:
            title = m.group(1); i += 1
            if i < len(L) and L[i] == "Votes": i += 1
            cands = []
            while i + 2 < len(L) and re.fullmatch(r"[\d.]+%", L[i + 1]) and re.fullmatch(r"\d+", L[i + 2]):
                cands.append({"label": L[i], "votes": int(L[i + 2]), "pct": float(L[i + 1][:-1])}); i += 3
            rep = re.search(r"Precincts Reporting (\d+) of (\d+)", " ".join(L[i:i + 3]))
            out[title] = {"candidates": cands, "reporting": [int(rep.group(1)), int(rep.group(2))] if rep else None}
        else: i += 1
    return {"name": "Jefferson County Clerk, unofficial results", "url": JEFFERSON_URL, "as_of_note": as_of, "contests": out}

# ---------- Dodge County: summary PDF on the clerk's page ----------
DODGE_PDF = "https://www.co.dodge.wi.gov/fs/resource-manager/view/22b21b2e-4ae4-4868-a0cd-449d43dad477"
DODGE_PAGE = "https://www.co.dodge.wi.gov/government/county-clerk/elections-voting"
def dodge():
    from pypdf import PdfReader
    r = _get(DODGE_PDF)
    pdf = PdfReader(io.BytesIO(r.content))
    L = []
    for p in pdf.pages: L += [l.rstrip() for l in (p.extract_text(extraction_mode="layout") or "").split("\n") if l.strip()]
    foot = next((l.strip() for l in L if "Election Summary -" in l), "")
    as_of = re.search(r"Election Summary - (.+?)\s+Page", foot)
    out, i = {}, 0
    while i < len(L):
        if L[i].strip().startswith("Vote For 1") and i > 0:
            title = L[i - 1].strip(); i += 1
            cands, rep = [], None
            while i < len(L) and not L[i].strip().startswith("Vote For 1"):
                s = L[i].strip()
                m = re.match(r"(.+?)\s{2,}([\d,]+)\s+([\d.]+)%$", s)
                if m and not s.startswith(("Total Votes", "Contest Totals")): cands.append({"label": m.group(1).strip(), "votes": _num(m.group(2)), "pct": float(m.group(3))})
                mm = re.search(r"Precincts Reporting\s+(\d+) of (\d+)", s)
                if mm: rep = [int(mm.group(1)), int(mm.group(2))]
                if rep and i + 1 < len(L) and not re.match(r"(Precincts|\s)", L[i + 1].strip()) and i + 2 < len(L) and L[i + 2].strip().startswith("Vote For 1"): break
                i += 1
            if cands: out[title] = {"candidates": cands, "reporting": rep}
        else: i += 1
    return {"name": "Dodge County Clerk, unofficial results (summary report PDF)", "url": DODGE_PAGE, "pdf": DODGE_PDF, "as_of_note": as_of.group(1) if as_of else "", "contests": out}

# ---------- NBC News race pages (vote data provided by The Associated Press) ----------
NBC = "https://www.nbcnews.com/politics/2026-elections/"
def _next_data(h):
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', h, re.S)
    return json.loads(m.group(1))
def nbc(slug):
    r = _get(NBC + slug); d = _next_data(r.text)["props"]["pageProps"]
    s = d["races"][0]["summary"]
    return {"name": "NBC News (vote data provided by The Associated Press)", "url": NBC + slug, "slug": slug,
            "page_updated": d.get("lastModified"), "call": s.get("callStatusText"), "pct_in": s.get("percentIn"), "total": s.get("votes"),
            "candidates": [{"label": c["name"], "votes": c["votes"], "pct": c["percentVote"], "winner": bool(c.get("isWinner")), "party": c.get("party")} for c in s["candidates"]]}


STATE_SLUGS = {"AL":"alabama","AK":"alaska","AZ":"arizona","AR":"arkansas","CA":"california","CO":"colorado","CT":"connecticut","DE":"delaware","FL":"florida","GA":"georgia","HI":"hawaii","ID":"idaho","IL":"illinois","IN":"indiana","IA":"iowa","KS":"kansas","KY":"kentucky","LA":"louisiana","ME":"maine","MD":"maryland","MA":"massachusetts","MI":"michigan","MN":"minnesota","MS":"mississippi","MO":"missouri","MT":"montana","NE":"nebraska","NV":"nevada","NH":"new-hampshire","NJ":"new-jersey","NM":"new-mexico","NY":"new-york","NC":"north-carolina","ND":"north-dakota","OH":"ohio","OK":"oklahoma","OR":"oregon","PA":"pennsylvania","RI":"rhode-island","SC":"south-carolina","SD":"south-dakota","TN":"tennessee","TX":"texas","UT":"utah","VT":"vermont","VA":"virginia","WA":"washington","WV":"west-virginia","WI":"wisconsin","WY":"wyoming"}
def nbc_state_house(st):
    """Every U.S. House race in one state, from NBC's state hub page (AP vote data)."""
    r = _get(NBC + STATE_SLUGS[st] + "-results"); d = _next_data(r.text)["props"]["pageProps"]
    out = {}
    for x in d.get("stateRaceResults", {}).get("house", []) or []:
        dn = x.get("district")
        if dn is None or not x.get("candidates"): continue
        out[f"{st}-{int(dn):02d}" if int(dn) else f"{st}-00"] = {
            "url": "https://www.nbcnews.com" + x["href"] if x.get("href") else NBC + STATE_SLUGS[st] + "-results", "page_updated": d.get("lastModified"),
            "pct_in": x.get("percentIn"), "total": x.get("votes"), "ranked_choice": bool(x.get("isRankedChoiceVotingRace")),
            "candidates": [{"label": c["name"], "votes": c["votes"], "pct": c.get("percentVote"), "winner": bool(c.get("isWinner")), "party": c.get("party"), "incumbent": bool(c.get("isIncumbent"))} for c in x["candidates"]]}
    if len(out) == 1:   # at-large state: the site keys these ST-00
        (k, v), = out.items(); out = {f"{st}-00": v}
    return out

# ---------- Exa Library contest pages (aggregator; matches AP/NBC where both publish) ----------
EXA = "https://exa.ai/library/election/contest/"
def exa(cid):
    L = _text(_get(EXA + cid).text)
    t = " | ".join(L)
    head = next((l for l in L if "general election" in l.lower() or "results" in l.lower()), "")
    i = L.index("Results") if "Results" in L else 0
    j = next(k for k in range(i, len(L)) if L[k].startswith("Votes are being counted") or L[k] == "Total" or L[k].startswith("How the count changed"))
    pct_in = None
    for l in L[i:i + 3]:
        m = re.fullmatch(r"(\d+)%", l)
        if m: pct_in = int(m.group(1))
    # table: after header "Share", repeated [name, (party?), votes, share%]
    k = L.index("Share", i) + 1 if "Share" in L[i:] else i
    cands = []
    while k < len(L) and L[k] != "Total":
        name = L[k]; k += 1
        party = None
        if not re.fullmatch(r"[\d,]+", L[k]): party = L[k]; k += 1
        votes = _num(L[k]); pct = float(L[k + 1].rstrip("%")); k += 2
        cands.append({"label": name, "party_text": party, "votes": votes, "pct": pct})
    total = _num(L[k + 1]) if k + 1 < len(L) and L[k] == "Total" else None
    upd = next((re.search(r"Updated (.+)", l).group(1) for l in L if l.startswith("Votes are being counted") or "Updated November" in l), "")
    upd = re.search(r"Updated (November \d+, 2026, [\d:]+ [AP]M [A-Z]{2,3})", t)
    called = re.search(r"Called (November \d+, 2026, [\d:]+ [AP]M [A-Z]{2,3})", t)
    outcome = re.search(r"\b(Passed|Failed)\b", t)
    return {"name": "Exa Library election results (aggregated vote data)", "url": EXA + cid, "id": cid, "pct_in": pct_in, "total": total,
            "updated": upd.group(1) if upd else "", "called": called.group(1) if called else "", "outcome": outcome.group(1) if outcome else "",
            "unnamed_winner": bool(re.search(r"\bwon\b|Winner|Called for", t)), "candidates": cands}

if __name__ == "__main__":
    import sys
    for fn in (waukesha, jefferson, dodge):
        d = fn(); print("==", d["name"], d["as_of_note"], len(d["contests"]))
        for k, v in d["contests"].items(): print("  ", k, v["reporting"], [(c["label"], c["votes"], c["pct"]) for c in v["candidates"]])
    for s in ("wisconsin-governor-results", "wisconsin-us-house-district-5-results"): print(nbc(s))
    for c in ("43vxh5chqxp", "44lfghbctbz", "2vs6x29nhrp"): print(exa(c))
