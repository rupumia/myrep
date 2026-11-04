"""Nov 3, 2026 election results for the "On your ballot" section (Wisconsin) and U.S. House races (all states).

Build-time flow: try to refresh every source (each independently); anything that fails keeps its last committed
snapshot value (data_src/wi_results_2026.json) and is flagged with its own as-of time. Nothing is estimated. See
wi_results_src.py for the sources. Set WI_RESULTS_REFRESH=0 to build from the snapshot only.
"""
import os, re, json, datetime as dt
from zoneinfo import ZoneInfo
import wi_results_src as S

ROOT = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(ROOT, "data_src", "wi_results_2026.json")
CT = ZoneInfo("America/Chicago")
NBC_STATEWIDE = {"Governor / Lieutenant Governor (one ticket)": "wisconsin-governor-results", "Attorney General": "wisconsin-attorney-general-results",
                 "Secretary of State": "wisconsin-secretary-of-state-results"}
EXA_IDS = {"State Treasurer": "43vxh5chqxp", "State of Wisconsin Partial Veto Referendum": "2vs6x29nhrp",
           "State of Wisconsin Freedom to Gather in Places of Worship During an Emergency Referendum": "gh3l1fkgd54",
           "State of Wisconsin Governmental Entity Discrimination Prohibited Referendum": "ldb4mn914fg",
           "senate:33": "44lfghbctbz", "senate:7": "bwvpk5b853d", "assembly:19": "fxx8wvqh9qz"}
COUNTIES = ("Waukesha", "Jefferson", "Dodge")
PARTY = {"gop": "R", "dem": "D", "ind": "I", "other": ""}

# ---------------------------------------------------------------- refresh
def _try(log, label, fn, *a):
    try:
        v = fn(*a); v["fetched"] = S.now_utc(); return v
    except Exception as e:
        log(f"  results source FAILED ({label}): {type(e).__name__}: {str(e)[:120]}"); return None

def refresh(snap, log=print):
    snap.setdefault("election_date", "2026-11-03")
    src = snap.setdefault("sources", {})
    for k, fn in (("waukesha", S.waukesha), ("jefferson", S.jefferson), ("dodge", S.dodge)):
        v = _try(log, k, fn)
        if v and v["contests"]: src[k] = v
    nbc = src.setdefault("nbc", {})
    for slug in list(NBC_STATEWIDE.values()):
        v = _try(log, slug, S.nbc, slug)
        if v and v["candidates"]: nbc[slug] = v
    ex = src.setdefault("exa", {})
    for cid in set(EXA_IDS.values()):
        v = _try(log, "exa " + cid, S.exa, cid)
        if v and v["candidates"]: ex[cid] = v
    hs = src.setdefault("house", {})
    for st in S.STATE_SLUGS:
        v = _try(log, "house " + st, lambda s=st: {"races": S.nbc_state_house(s)})
        if v and v["races"]: hs[st] = v
    snap["refreshed"] = S.now_utc()
    return snap

def load(log=print):
    snap = json.load(open(SNAP)) if os.path.exists(SNAP) else {}
    if os.environ.get("WI_RESULTS_REFRESH", "1") != "0":
        try:
            refresh(snap, log)
            json.dump(snap, open(SNAP, "w"), indent=1, sort_keys=True)
        except Exception as e: log("  results refresh error:", e)
    return snap

# ---------------------------------------------------------------- helpers
def ct_label(iso_utc):
    try: d = dt.datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    except ValueError:
        from email.utils import parsedate_to_datetime
        d = parsedate_to_datetime(iso_utc)
    d = d.astimezone(CT)
    return d.strftime("%b %-d, %-I:%M %p ") + ("CDT" if d.dst() else "CST")
def exa_label(s):   # "November 4, 2026, 1:04 PM EST" -> Central
    m = re.match(r"(\w+ \d+, \d{4}), (\d+:\d+ [AP]M) (E[SD]T)", s or "")
    if not m: return s or ""
    d = dt.datetime.strptime(f"{m.group(1)} {m.group(2)}", "%B %d, %Y %I:%M %p")
    d = d.replace(tzinfo=dt.timezone(dt.timedelta(hours=-5 if m.group(3) == "EST" else -4))).astimezone(CT)
    return d.strftime("%b %-d, %-I:%M %p ") + ("CDT" if d.dst() else "CST")
def _name_keys(name):
    name = re.sub(r"^(REP|DEM|WGR|WGN|IND|LIB|CON|NPA|GRN)\s+", "", name.strip())
    keys = set()
    for part in name.split("/"):
        toks = [t for t in re.split(r"[\s-]+", part.strip()) if t]
        if toks: keys.add(re.sub(r"[^a-z]", "", toks[-1].lower()))
    return keys
def _is_write(label): return label.lower().startswith("write")

def _rows(cands, ballot_cands, yesno=False):
    """cands: source rows; ballot_cands: WEC candidates [{name,abbr,party}] used for display names and neutral party labels."""
    rows = []
    for c in cands:
        r = {"votes": c["votes"], "pct": c.get("pct")}
        if yesno or c["label"] in ("Yes", "No"): r["name"] = c["label"]
        elif _is_write(c["label"]): r["name"] = "Write-in votes"; r["write_in"] = True
        else:
            k = _name_keys(c["label"])
            b = next((b for b in ballot_cands if _name_keys(b["name"]) & k), None)
            r["name"] = b["name"] if b else re.sub(r"^(REP|DEM|WGR|WGN|IND|LIB|CON)\s+", "", c["label"])
            r["abbr"] = (b or {}).get("abbr") or PARTY.get(c.get("party") or "", "")
            if b and b.get("abbr") is None: r["abbr"] = b.get("party")
            if "winner" in c: r["winner"] = c["winner"]
        rows.append(r)
    return rows

def _county_part(county, srcname, src, key, ballot_cands, yesno=False):
    c = src["contests"].get(key)
    if not c: return None
    asof = src["as_of_note"]
    if county == "Jefferson": asof = _fmt_mdy(asof, "%m-%d-%Y %I:%M %p") + " (county page)"
    elif county == "Dodge": asof = _fmt_mdy(asof, "%m/%d/%Y %I:%M%p") + " (report footer)"
    else: asof = f"{asof.replace('Unofficial Results - ', '').rstrip('.')} (county page; fetched {ct_label(src['fetched'])})"
    return {"county": county + " County", "source": src["name"], "url": src["url"], "as_of": asof,
            "reporting": c.get("reporting"), "candidates": _rows(c["candidates"], ballot_cands, yesno)}
def _fmt_mdy(s, fmt):
    try: return dt.datetime.strptime(s.strip(), fmt).strftime("%b %-d, %-I:%M %p CT")
    except Exception: return s

# county-source key lookup
def _find(src, pats):
    for k in src["contests"]:
        if any(re.fullmatch(p, k, re.I) for p in pats): return k
def _dist_pat(kind, n):
    n = str(int(n))
    return {"senate": [rf"State Senator District {n}", rf"St Senator Dist {n}", rf"Senate Dist {n}", rf"State Sen - Dist {n}", rf"Senator Dist {n}"],
            "assembly": [rf"Representative to the Assembly District {n}", rf"Assembly Dist {n}", rf"Rep Assem {n}"],
            "house": [rf"Representative in Congress District {n}", rf"Rep in Congress Dist {n}", rf"Rep Congress Dis {n}"]}[kind]
STATE_PATS = {
    "Governor / Lieutenant Governor (one ticket)": [r"Governor.*"], "Attorney General": [r"Attorney Gen(eral)?", r"Atty General"],
    "Secretary of State": [r"Secretary of State", r"Sec of State", r"Sec State"], "State Treasurer": [r"State Treasurer", r"St Treasurer", r"State Treas\."],
    "State of Wisconsin Partial Veto Referendum": [r"Question 1", r"State Ref - Question #1", r"State Q1"],
    "State of Wisconsin Freedom to Gather in Places of Worship During an Emergency Referendum": [r"Question 2", r"State Ref - Question #2", r"State Q2"],
    "State of Wisconsin Governmental Entity Discrimination Prohibited Referendum": [r"Question 3", r"State Ref - Question #3", r"State Q3"]}
OFFICE_PATS = {"Sheriff": [r"Sheriff.*"], "Clerk of Circuit Court": [r"Clerk of Circuit Court", r"Clerk of Court", r"Circuit Court Clerk.*"]}
OASD_PATS = [r"Oconomowoc Area School Referendum", r"Ocon School Ref", r"Ocon SD Ref"]

def _parts(src_all, pats, ballot_cands, yesno=False, counties=COUNTIES):
    out = []
    for cty in counties:
        s = src_all.get(cty.lower())
        if not s: continue
        k = _find(s, pats)
        if k:
            p = _county_part(cty, s["name"], s, k, ballot_cands, yesno)
            if p: out.append(p)
    return out

def _called_result(kind, rows, *, winner_name, status, source, url, as_of, pct_in=None, total=None, call_note="", parts=None, note=""):
    return {"status": status, "winner": winner_name, "rows": rows, "source": source, "url": url, "as_of": as_of, "pct_in": pct_in, "total": total,
            "call_note": call_note, "parts": parts or [], "note": note}

def _from_nbc(v, ballot_cands):
    rows = _rows(v["candidates"], ballot_cands)
    for r, c in zip(rows, v["candidates"]): r["winner"] = bool(c.get("winner"))
    w = next((r["name"] for r in rows if r["winner"]), None)
    return dict(rows=rows, winner_name=w, status="called" if w else "counting", source=v["name"], url=v["url"], as_of=ct_label(v["page_updated"]),
                pct_in=v.get("pct_in"), total=v.get("total"), call_note=("Called: NBC News projection using AP vote data" if w else "Not called"))
def _from_exa(v, ballot_cands, yesno=False):
    rows = _rows(v["candidates"], ballot_cands, yesno)
    top = max(rows, key=lambda r: r["votes"])
    if yesno:
        called = bool(v["called"]) and v["outcome"] in ("Passed", "Failed")
        for r in rows: r["winner"] = False
        status = v["outcome"].lower() if called else "counting"
        w = None
        note = f"{v['outcome']}; called {exa_label(v['called'])}" if called else "Not called"
    else:
        called = bool(v["called"])
        for r in rows: r["winner"] = called and r is top
        status = "called" if called else "counting"; w = top["name"] if called else None
        note = f"Called {exa_label(v['called'])} (per Exa Library)" if called else "Not called"
    return dict(rows=rows, winner_name=w, status=status, source=v["name"], url=v["url"], as_of=exa_label(v["updated"]), pct_in=v.get("pct_in"), total=v.get("total"), call_note=note)

def _county_only(parts, ballot_cands, label_unopposed=False):
    return parts

def _result(d, parts):
    d = dict(d); d["parts"] = parts; d["winner"] = d.pop("winner_name", None); d.setdefault("note", ""); return d

# ---------------------------------------------------------------- attach to ballot JSON
def attach(out, snap, log=print):
    src = snap.get("sources", {})
    if not src: return {}
    cty = {k: src[k] for k in ("waukesha", "jefferson", "dodge") if k in src}
    nbc, exa = src.get("nbc", {}), src.get("exa", {})
    n = 0
    def unopposed(c, parts):
        if len(c["candidates"]) != 1: return None
        rows = parts[0]["candidates"] if parts else []
        return {"status": "unopposed", "winner": None, "rows": [], "source": "", "url": "", "as_of": "", "pct_in": None, "total": None, "call_note": "Unopposed", "parts": parts, "note": ""}
    # statewide offices and questions
    for c in out["statewide"]:
        o, bc = c["office"], c.get("candidates", [])
        yn = c.get("question") is not None
        parts = _parts(cty, STATE_PATS[o], bc, yesno=yn)
        slug = NBC_STATEWIDE.get(o)
        if slug and slug in nbc: c["result"] = _result(_from_nbc(nbc[slug], bc), parts)
        elif o in EXA_IDS and EXA_IDS[o] in exa: c["result"] = _result(_from_exa(exa[EXA_IDS[o]], bc, yn), parts)
        if "result" in c: n += 1
    # U.S. House (WI) from NBC hub
    wih = src.get("house", {}).get("WI", {}).get("races", {})
    for dn, c in out["house"].items():
        v = wih.get(f"WI-{dn}")
        parts = _parts(cty, _dist_pat("house", dn), c["candidates"])
        if v and len(v["candidates"]) > 1:
            d = _from_nbc({**v, "name": "NBC News (vote data provided by The Associated Press)", "page_updated": v["page_updated"]}, c["candidates"])
            c["result"] = _result(d, parts); n += 1
        elif v:
            c["result"] = {"status": "unopposed", "winner": None, "rows": [], "source": "NBC News (vote data provided by The Associated Press)", "url": v["url"], "as_of": ct_label(v["page_updated"]), "pct_in": None, "total": None, "call_note": "Unopposed", "parts": parts, "note": ""}; n += 1
        elif parts: c["result"] = _no_total(parts); n += 1
    # state legislature
    for kind, tbl in (("senate", out["senate"]), ("assembly", out["assembly"])):
        for dn, c in tbl.items():
            parts = _parts(cty, _dist_pat(kind, dn), c["candidates"])
            eid = EXA_IDS.get(f"{kind}:{int(dn)}")
            if len(c["candidates"]) == 1: c["result"] = {"status": "unopposed", "winner": None, "rows": [], "source": "", "url": "", "as_of": "", "pct_in": None, "total": None, "call_note": "Unopposed", "parts": parts, "note": "Counts below are the county returns for this district; they may not be the full district."} ; n += 1
            elif eid and eid in exa: c["result"] = _result(_from_exa(exa[eid], c["candidates"]), parts); n += 1
            elif parts: c["result"] = _no_total(parts); n += 1
    # county offices
    for cname, lst in out["county"].items():
        short = cname.replace(" County", "")
        for c in lst:
            if short.lower() not in cty: continue
            office = next((k for k in OFFICE_PATS if c["office"].endswith(k)), None)
            if not office: continue
            parts = _parts(cty, OFFICE_PATS[office], c["candidates"], counties=(short,))
            if not parts: continue
            if len(c["candidates"]) == 1:
                c["result"] = {"status": "unopposed", "winner": None, "rows": parts[0]["candidates"], "source": parts[0]["source"], "url": parts[0]["url"], "as_of": parts[0]["as_of"], "pct_in": None, "total": None, "call_note": "Unopposed", "parts": [], "note": "Votes shown include write-ins."}
            else: c["result"] = _no_total(parts)
            n += 1
    # Oconomowoc Area School District referendum: sum of the three county returns (checked against press totals)
    for lst in out["local"].values():
        for c in lst:
            if c["office"].startswith("Oconomowoc Area School District Exceed Revenue Limit"):
                parts = _parts(cty, OASD_PATS, [], yesno=True)
                if len(parts) == 3 and all(p["reporting"] and p["reporting"][0] == p["reporting"][1] for p in parts):
                    tot = {k: sum(r["votes"] for p in parts for r in p["candidates"] if r["name"] == k) for k in ("Yes", "No")}
                    t = tot["Yes"] + tot["No"]
                    rows = [{"name": k, "votes": tot[k], "pct": round(100 * tot[k] / t, 1), "winner": False} for k in ("Yes", "No")]
                    failed = tot["No"] > tot["Yes"]
                    c["result"] = {"status": "failed" if failed else "passed", "winner": None, "rows": rows,
                        "source": "Sum of the Waukesha, Jefferson and Dodge county clerks' unofficial results", "url": "", "as_of": "see counties below", "pct_in": 100, "total": t,
                        "call_note": f"All {sum(p['reporting'][1] for p in parts)} reporting units in the three counties are counted. Local news also reports the referendum {'failing' if failed else 'passing'}: ",
                        "news": {"label": "Oconomowoc Enterprise (gmtoday.com): \u201cOASD $12.2M referendum fails at the polls\u201d", "url": "https://www.gmtoday.com/oconomowoc_enterprise/news/oconomowoc-referendum-fails/article_0f9b5e0a-4284-46a0-a77a-6e496cf6274c.html"},
                        "parts": parts, "note": "Percentages computed from the summed county vote counts."}
                    n += 1
                elif parts: c["result"] = _no_total(parts); n += 1
    # contests with a single candidate on the WEC list but no vote counts loaded: still say "Unopposed"
    def rest(c):
        if "result" not in c and c.get("question") is None and len(c.get("candidates", [])) == 1:
            c["result"] = {"status": "unopposed", "winner": None, "rows": [], "source": "", "url": "", "as_of": "", "pct_in": None, "total": None,
                           "call_note": "Unopposed", "parts": [], "note": "Vote totals for this contest are not loaded on MyRep; see the county clerk's results."}
    for c in list(out["house"].values()) + list(out["senate"].values()) + list(out["assembly"].values()): rest(c)
    for tbl in (out["county"], out["local"]):
        for lst in tbl.values():
            for c in lst: rest(c)
    log(f"  results attached to {n} ballot contests")
    return {"results_refreshed": snap.get("refreshed")}

def _no_total(parts):
    return {"status": "counties_only", "winner": None, "rows": [], "source": "", "url": "", "as_of": "", "pct_in": None, "total": None,
            "call_note": "No source used by MyRep has called this race or published a district-wide total. County returns for the counties covered are shown.", "parts": parts, "note": ""}

# ---------------------------------------------------------------- U.S. House, all states
def build_house(write_json, snap, log=print):
    out = {}
    for st, v in snap.get("sources", {}).get("house", {}).items():
        for k, r in v["races"].items():
            cs = r["candidates"]
            w = next((c["label"] for c in cs if c["winner"]), None)
            out[k] = {"status": "unopposed" if len(cs) == 1 else ("called" if w else "counting"), "winner": w, "pct_in": r["pct_in"], "total": r["total"], "url": r["url"],
                      "as_of": ct_label(r["page_updated"]), "ranked_choice": r["ranked_choice"],
                      "rows": [{"name": c["label"], "abbr": PARTY.get(c.get("party") or "", ""), "votes": c["votes"], "pct": c["pct"], "winner": c["winner"], "incumbent": c.get("incumbent", False)} for c in cs]}
    if out:
        write_json("results/house.json", {"source": "NBC News (vote data provided by The Associated Press)", "races": out})
    log(f"  House results: {len(out)} races")
    return len(out)
