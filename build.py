#!/usr/bin/env python3
"""MyRep static-site builder.

Downloads free public data, precomputes JSON, and writes a deployable static
site into ./site. No live API calls are made by the frontend.

Sources:
  * unitedstates/congress-legislators  (current members, bioguide/FEC/ICPSR ids)
  * Census 2020 ZCTA <-> 119th Congressional District relationship file
  * House Clerk roll-call XML  (clerk.house.gov/evs/<year>/rollNNN.xml)
  * Voteview Senate roll calls + member votes (mirror of Senate LIS data)
  * FEC bulk files for the 2025-2026 cycle (weball, cn, cm, pas2)
  * FEC API (api.open.fec.gov) for top contributor employers, paced + cached

Env vars:
  FEC_API_KEY       free key from https://api.data.gov/signup (default DEMO_KEY)
  FEC_MAX_CALLS     max FEC API calls per build (default 900 with a key, 8 with DEMO_KEY)
  FEC_CALL_INTERVAL seconds between FEC calls (default 4.0 with a key, 2.0 with DEMO_KEY)
  PRIORITY_ZIPS     comma list of ZIPs whose seats get FEC API calls first
  VOTES_PER_MEMBER  recent roll calls stored per member (default 30)
  OFFLINE=1         reuse cached raw downloads, no network refetch of bulk files
"""
import csv, io, json, os, re, shutil, sys, time, zipfile, datetime as dt
from collections import defaultdict
import xml.etree.ElementTree as ET
import requests
import aipac
import israel
import districts2026

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, "cache", "raw")
HOUSE_CACHE = os.path.join(ROOT, "cache", "house")
EMP_CACHE = os.path.join(ROOT, "cache", "fec_employers.json")
SITE = os.path.join(ROOT, "site")
OUT = os.path.join(SITE, "data")
CYCLE = 2026
CONGRESS = 119
UA = {"User-Agent": "MyRep civic data builder (open source; contact via repo)"}
VOTES_PER_MEMBER = int(os.environ.get("VOTES_PER_MEMBER", "30"))
OFFLINE = os.environ.get("OFFLINE") == "1"
FEC_KEY = os.environ.get("FEC_API_KEY") or "DEMO_KEY"
DEMO = FEC_KEY == "DEMO_KEY"
FEC_MAX_CALLS = int(os.environ.get("FEC_MAX_CALLS", "8" if DEMO else "900"))
FEC_INTERVAL = float(os.environ.get("FEC_CALL_INTERVAL", "2.0" if DEMO else "4.0"))
PRIORITY_ZIPS = [z.strip() for z in os.environ.get("PRIORITY_ZIPS", "").split(",") if z.strip()]

FIPS = {"01":"AL","02":"AK","04":"AZ","05":"AR","06":"CA","08":"CO","09":"CT","10":"DE","11":"DC","12":"FL","13":"GA","15":"HI","16":"ID","17":"IL","18":"IN","19":"IA","20":"KS","21":"KY","22":"LA","23":"ME","24":"MD","25":"MA","26":"MI","27":"MN","28":"MS","29":"MO","30":"MT","31":"NE","32":"NV","33":"NH","34":"NJ","35":"NM","36":"NY","37":"NC","38":"ND","39":"OH","40":"OK","41":"OR","42":"PA","44":"RI","45":"SC","46":"SD","47":"TN","48":"TX","49":"UT","50":"VT","51":"VA","53":"WA","54":"WV","55":"WI","56":"WY","60":"AS","66":"GU","69":"MP","72":"PR","78":"VI"}
STATE_NAMES = {"AL":"Alabama","AK":"Alaska","AZ":"Arizona","AR":"Arkansas","CA":"California","CO":"Colorado","CT":"Connecticut","DE":"Delaware","DC":"District of Columbia","FL":"Florida","GA":"Georgia","HI":"Hawaii","ID":"Idaho","IL":"Illinois","IN":"Indiana","IA":"Iowa","KS":"Kansas","KY":"Kentucky","LA":"Louisiana","ME":"Maine","MD":"Maryland","MA":"Massachusetts","MI":"Michigan","MN":"Minnesota","MS":"Mississippi","MO":"Missouri","MT":"Montana","NE":"Nebraska","NV":"Nevada","NH":"New Hampshire","NJ":"New Jersey","NM":"New Mexico","NY":"New York","NC":"North Carolina","ND":"North Dakota","OH":"Ohio","OK":"Oklahoma","OR":"Oregon","PA":"Pennsylvania","RI":"Rhode Island","SC":"South Carolina","SD":"South Dakota","TN":"Tennessee","TX":"Texas","UT":"Utah","VT":"Vermont","VA":"Virginia","WA":"Washington","WV":"West Virginia","WI":"Wisconsin","WY":"Wyoming","AS":"American Samoa","GU":"Guam","MP":"Northern Mariana Islands","PR":"Puerto Rico","VI":"U.S. Virgin Islands"}
PARTY_ABBR = {"Democrat":"D","Republican":"R","Independent":"I","DEM":"D","REP":"R","IND":"I","DFL":"D","LIB":"L","GRE":"G","CON":"C","NNE":"None","NPA":"NPA","UN":"U","OTH":"Other"}

meta = {"built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "sources": {}, "warnings": [], "israel_rollcalls": {}}
S = requests.Session(); S.headers.update(UA)

def log(*a): print("[build]", *a, flush=True)

def fetch(url, dest, binary=True, timeout=120):
    path = os.path.join(RAW, dest)
    if OFFLINE and os.path.exists(path):
        return path
    r = S.get(url, timeout=timeout); r.raise_for_status()
    with open(path, "wb") as f: f.write(r.content)
    return path

def write_json(rel, obj):
    p = os.path.join(OUT, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f: json.dump(obj, f, separators=(",", ":"))

def money(x):
    try: return round(float(x or 0), 2)
    except ValueError: return 0.0

# ---------------------------------------------------------------- legislators
def load_legislators():
    p = fetch("https://unitedstates.github.io/congress-legislators/legislators-current.json", "legislators-current.json")
    data = json.load(open(p))
    meta["sources"]["legislators"] = {"name": "unitedstates/congress-legislators (legislators-current.json)",
        "url": "https://github.com/unitedstates/congress-legislators", "retrieved": meta["built_at"][:10]}
    members = {}
    for m in data:
        t = m["terms"][-1]
        members[m["id"]["bioguide"]] = {
            "bioguide": m["id"]["bioguide"],
            "name": m["name"].get("official_full") or f'{m["name"]["first"]} {m["name"]["last"]}',
            "last": m["name"]["last"],
            "party": t.get("party"), "party_abbr": PARTY_ABBR.get(t.get("party"), t.get("party", "")[:1]),
            "chamber": "senate" if t["type"] == "sen" else "house",
            "state": t["state"], "district": t.get("district"),
            "senate_class": t.get("class"), "state_rank": t.get("state_rank"),
            "term_start": t["start"], "term_end": t["end"], "how": t.get("how"),
            "url": t.get("url"), "phone": t.get("phone"), "office": t.get("address") or t.get("office"),
            "fec_ids": m["id"].get("fec", []), "icpsr": m["id"].get("icpsr"),
            "photo": f'https://unitedstates.github.io/images/congress/225x275/{m["id"]["bioguide"]}.jpg',
            "bioguide_url": f'https://bioguide.congress.gov/search/bio/{m["id"]["bioguide"]}',
            "title": "Senator" if t["type"] == "sen" else ("Delegate" if t["state"] in ("DC","AS","GU","MP","VI") else ("Resident Commissioner" if t["state"] == "PR" else "Representative")),
        }
    log(len(members), "current members")
    return members

# ------------------------------------------------------------ zip -> district
def build_zips():
    try:
        cd120 = districts2026.compute(RAW, FIPS, log=log)
        meta["sources"]["zip_2026"] = {"name": "Derived: Census 2020 ZCTA boundaries overlaid on TIGER/Line 2026 (120th Congress) district boundaries, for states that redrew",
            "url": "https://www2.census.gov/geo/tiger/TIGER2026/CD/", "retrieved": meta["built_at"][:10]}
    except Exception as e:
        log("2026 district overlay FAILED", e); meta["warnings"].append(f"2026 district mapping unavailable: {e}")
        cd120 = {"changed_states": [], "zips": {}, "failed": True}
    changed = set(cd120["changed_states"])
    p = fetch("https://www2.census.gov/geo/docs/maps-data/data/rel2020/cd-sld/tab20_cd11920_zcta520_natl.txt", "zcta_cd119.txt")
    meta["sources"]["zip"] = {"name": "U.S. Census Bureau 2020 ZCTA to 119th Congressional District relationship file",
        "url": "https://www2.census.gov/geo/docs/maps-data/data/rel2020/cd-sld/", "retrieved": meta["built_at"][:10]}
    z = defaultdict(list)
    with open(p, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f, delimiter="|"):
            zc = row["GEOID_ZCTA5_20"]; geo = row["GEOID_CD119_20"]
            if not zc or not geo: continue
            st = FIPS.get(geo[:2]); cd = geo[2:]
            if not st or cd == "ZZ": continue
            if cd == "98": cd = "00"  # DC / PR non-voting delegate = at-large
            z[zc].append((st, cd, int(row["AREALAND_PART"] or 0), int(row["AREALAND_ZCTA5_20"] or 0)))
    shards = defaultdict(dict)
    for zc, parts in z.items():
        total = sum(p[2] for p in parts) or 1
        keep = [p for p in parts if p[2] > 0] or parts
        entry = {"d": sorted([{"state": s, "district": d, "land_share": round(a / total, 3)} for s, d, a, _ in keep], key=lambda x: -x["land_share"])}
        if any(x["state"] in changed for x in entry["d"]):
            d26 = cd120["zips"].get(zc)
            entry["d26"] = d26 if d26 else None  # None = could not be derived -> frontend shows 'unavailable'
        shards[zc[:3]][zc] = entry
    for k, v in shards.items(): write_json(f"zip/{k}.json", v)
    meta["redistricted_2026"] = sorted(changed)
    meta["zip_prefixes"] = sorted(shards)
    log(len(z), "ZCTAs,", sum(1 for v in z.values() if len(v) > 1), "split across districts")
    return z, cd120

# ---------------------------------------------------------------- house votes
def house_roll(year, n):
    d = os.path.join(HOUSE_CACHE, str(year)); os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"roll{n:03d}.xml")
    if os.path.exists(p):
        return open(p, "rb").read()
    r = S.get(f"https://clerk.house.gov/evs/{year}/roll{n:03d}.xml", timeout=60)
    if r.status_code != 200 or b"<rollcall-vote" not in r.content:
        return None
    with open(p, "wb") as f: f.write(r.content)
    return r.content

def house_max_roll(year):
    def exists(n):
        r = S.get(f"https://clerk.house.gov/evs/{year}/roll{n:03d}.xml", timeout=60)
        return r.status_code == 200 and b"<rollcall-vote" in r.content
    if not exists(1): return 0
    lo, hi = 1, 2
    while exists(hi): lo, hi = hi, hi * 2
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if exists(mid): lo = mid
        else: hi = mid
    return lo

def bill_link(legis):
    m = re.match(r"^(H R|S|H RES|S RES|H J RES|S J RES|H CON RES|S CON RES|HR|HRES|HJRES|SJRES|SRES|HCONRES|SCONRES)\s*(\d+)$", (legis or "").upper().strip())
    if not m: return None
    kind = m.group(1).replace(" ", "")
    path = {"HR":"house-bill","S":"senate-bill","HRES":"house-resolution","SRES":"senate-resolution","HJRES":"house-joint-resolution",
            "SJRES":"senate-joint-resolution","HCONRES":"house-concurrent-resolution","SCONRES":"senate-concurrent-resolution"}[kind]
    return f"https://www.congress.gov/bill/{CONGRESS}th-congress/{path}/{m.group(2)}"

def norm_vote(v):
    v = (v or "").strip()
    return {"Aye": "Yea", "No": "Nay", "Yea": "Yea", "Nay": "Nay"}.get(v, v or "Not Voting")

def house_israel_rolls():
    """(year, roll) -> {"title", "terms"} for every House roll call of this Congress, classified Israel-related or not."""
    texts = {}
    try:
        ct = israel.CongressText(os.path.join(ROOT, "cache"), os.environ.get("CONGRESS_API_KEY") or FEC_KEY,
                                 interval=float(os.environ.get("CONGRESS_CALL_INTERVAL", "0.8")), log=log)
        texts = israel.house_roll_text(ct, CONGRESS, 2025, log=log)
        meta["sources"]["congress_gov"] = {"name": "congress.gov API: House roll-call metadata, bill titles and amendment purposes (used for vote topics)",
            "url": "https://api.congress.gov/", "calls_this_build": ct.calls, "stopped_reason": ct.stopped, "retrieved": meta["built_at"][:10]}
        log(f"israel: congress.gov {ct.calls} calls, {len(texts)} House roll calls with text, stop: {ct.stopped}")
    except Exception as e:
        log("congress.gov text FAILED", e); meta["warnings"].append(f"congress.gov bill titles unavailable this build: {e}")
    try:
        vv = list(csv.DictReader(open(fetch(f"https://voteview.com/static/data/out/rollcalls/H{CONGRESS}_rollcalls.csv", f"H{CONGRESS}_rollcalls.csv"))))
        for r in vv:
            k = (int(r["date"][:4]), int(r["clerk_rollnumber"]))
            texts.setdefault(k, {"title": "", "texts": []})["texts"] += [r["vote_desc"], r["dtl_desc"]]
            if not texts[k]["title"]: texts[k]["title"] = r["vote_desc"]
    except Exception as e:
        log("Voteview House rollcalls FAILED", e)
    return {k: {"title": v["title"], "terms": israel.match(*v["texts"])} for k, v in texts.items()}

def build_house_votes():
    year = dt.date.today().year
    rolls = []
    for y in (year, year - 1):
        if y < 2025 or len(rolls) >= VOTES_PER_MEMBER * 2: break
        mx = house_max_roll(y)
        log("House", y, "max roll", mx)
        n = mx
        while n >= 1 and len(rolls) < VOTES_PER_MEMBER * 2:
            x = house_roll(y, n)
            if x: rolls.append((y, n, x))
            n -= 1
    topics = house_israel_rolls()
    have = {(y, n) for y, n, _ in rolls}
    for (y, n), t in sorted(topics.items()):
        if t["terms"] and (y, n) not in have:
            x = house_roll(y, n)
            if x: rolls.append((y, n, x))
    by_member = defaultdict(list); latest = None; n_isr = 0
    for y, n, x in rolls:
        root = ET.fromstring(x); md = root.find("vote-metadata")
        if (md.findtext("vote-type") or "").upper() == "QUORUM": continue
        date = dt.datetime.strptime(md.findtext("action-date"), "%d-%b-%Y").date().isoformat()
        latest = max(latest or date, date)
        legis = md.findtext("legis-num") or ""
        tot = md.find("vote-totals/totals-by-vote")
        t = topics.get((y, n), {"title": "", "terms": []})
        q = md.findtext("vote-question") or ""; desc = (md.findtext("vote-desc") or "").strip()
        terms = sorted(set(t["terms"]) | set(israel.match(q, desc, legis)))
        n_isr += bool(terms)
        info = {"chamber": "house", "roll": n, "year": y, "date": date,
                "bill": legis if legis and legis != "0" else "", "bill_url": bill_link(legis),
                "question": q, "description": desc or t["title"],
                "result": md.findtext("vote-result") or "",
                "yeas": int(tot.findtext("yea-total") or 0) if tot is not None else None,
                "nays": int(tot.findtext("nay-total") or 0) if tot is not None else None,
                "israel": bool(terms), "israel_terms": terms,
                "source_url": f"https://clerk.house.gov/Votes/{y}{n}"}
        for rv in root.iter("recorded-vote"):
            leg = rv.find("legislator"); bid = leg.get("name-id")
            by_member[bid].append(dict(info, vote=norm_vote(rv.findtext("vote"))))
    meta["israel_rollcalls"]["house"] = n_isr
    meta["sources"]["house_votes"] = {"name": "Office of the Clerk, U.S. House: roll-call vote XML", "url": "https://clerk.house.gov/Votes",
        "latest_vote_date": latest, "retrieved": meta["built_at"][:10]}
    return by_member

# --------------------------------------------------------------- senate votes
VV_CAST = {1:"Yea",2:"Yea",3:"Yea",4:"Nay",5:"Nay",6:"Nay",7:"Present",8:"Not Voting",9:"Not Voting",0:"Not a Member"}
def build_senate_votes():
    rc = fetch(f"https://voteview.com/static/data/out/rollcalls/S{CONGRESS}_rollcalls.csv", f"S{CONGRESS}_rollcalls.csv")
    vt = fetch(f"https://voteview.com/static/data/out/votes/S{CONGRESS}_votes.csv", f"S{CONGRESS}_votes.csv")
    mb = fetch(f"https://voteview.com/static/data/out/members/S{CONGRESS}_members.csv", f"S{CONGRESS}_members.csv")
    calls = list(csv.DictReader(open(rc)))
    calls.sort(key=lambda r: int(r["rollnumber"]))
    terms = {int(r["rollnumber"]): israel.match(r["vote_question"], r["vote_desc"], r.get("dtl_desc", "")) for r in calls}
    notes = {int(r["rollnumber"]): israel.package_note(r["vote_question"], r["vote_desc"], r.get("dtl_desc", ""))
             for r in calls if terms[int(r["rollnumber"])]}
    if any(notes.values()): log("israel: package notes on Voteview rollnumbers", [n for n in notes if notes[n]])
    recent = {int(r["rollnumber"]): r for r in calls[-VOTES_PER_MEMBER * 2:]}
    recent.update({int(r["rollnumber"]): r for r in calls if terms[int(r["rollnumber"])]})
    meta["israel_rollcalls"]["senate"] = sum(1 for t in terms.values() if t)
    icpsr2bio = {r["icpsr"]: r["bioguide_id"] for r in csv.DictReader(open(mb)) if r["bioguide_id"]}
    by_member = defaultdict(list); latest = max(r["date"] for r in calls) if calls else None
    for r in csv.DictReader(open(vt)):
        n = int(r["rollnumber"])
        if n not in recent: continue
        c = recent[n]; bid = icpsr2bio.get(r["icpsr"])
        if not bid: continue
        code = int(float(r["cast_code"]))
        if code == 0: continue
        year = int(c["date"][:4]); sess = int(c["session"]); cr = int(c["clerk_rollnumber"])
        by_member[bid].append({"chamber": "senate", "roll": cr, "year": year, "date": c["date"],
            "bill": c["bill_number"], "bill_url": bill_link(re.sub(r"^(HR|S|HRES|SRES|HJRES|SJRES|HCONRES|SCONRES)(\d+)$", r"\1 \2", c["bill_number"] or "")),
            "question": c["vote_question"], "description": c["vote_desc"], "result": c["vote_result"],
            "yeas": int(c["yea_count"]), "nays": int(c["nay_count"]), "vote": VV_CAST.get(code, "Unknown"),
            "israel": bool(terms[n]), "israel_terms": terms[n],
            **({"israel_note": notes[n]} if notes.get(n) else {}),
            "source_url": f"https://www.senate.gov/legislative/LIS/roll_call_votes/vote{CONGRESS}{sess}/vote_{CONGRESS}_{sess}_{cr:05d}.htm"})
    meta["sources"]["senate_votes"] = {"name": "Voteview (UCLA) Senate roll calls & member votes, mirroring official Senate LIS records",
        "url": "https://voteview.com/data", "latest_vote_date": latest, "retrieved": meta["built_at"][:10]}
    return by_member

# ------------------------------------------------------------------ FEC bulk
def fec_bulk(name, inner):
    yy = str(CYCLE)[2:]
    p = os.path.join(RAW, inner)
    if not (OFFLINE and os.path.exists(p)):
        r = S.get(f"https://www.fec.gov/files/bulk-downloads/{CYCLE}/{name}{yy}.zip", timeout=600); r.raise_for_status()
        zipfile.ZipFile(io.BytesIO(r.content)).extractall(RAW)
        meta["sources"].setdefault("fec_bulk_files", {})[name] = r.headers.get("Last-Modified")
    return p

def latest_cvg(weball):
    today = dt.date.today(); best = None
    for w in weball.values():
        try: d = dt.datetime.strptime(w["CVG_END_DT"], "%m/%d/%Y").date()
        except ValueError: continue
        if d <= today and (best is None or d > best): best = d
    return best.isoformat() if best else None

NON_EMPLOYERS = {"NOT EMPLOYED","NONE","RETIRED","SELF","SELF EMPLOYED","SELF-EMPLOYED","SELFEMPLOYED","N/A","NA","INFORMATION REQUESTED",
    "INFORMATION REQUESTED PER BEST EFFORTS","NULL","NOT EMPLOYED/RETIRED","NOT-EMPLOYED","DISABLED","REQUESTED","HOMEMAKER","UNEMPLOYED","NOT APPLICABLE","STUDENT","(BLANK)","","REFUSED","ENTREPRENEUR"}

def load_fec():
    W = ["CAND_ID","CAND_NAME","CAND_ICI","PTY_CD","CAND_PTY_AFFILIATION","TTL_RECEIPTS","TRANS_FROM_AUTH","TTL_DISB","TRANS_TO_AUTH","COH_BOP","COH_COP","CAND_CONTRIB","CAND_LOANS","OTHER_LOANS","CAND_LOAN_REPAY","OTHER_LOAN_REPAY","DEBTS_OWED_BY","TTL_INDIV_CONTRIB","CAND_OFFICE_ST","CAND_OFFICE_DISTRICT","SPEC_ELECTION","PRIM_ELECTION","RUN_ELECTION","GEN_ELECTION","GEN_ELECTION_PRECENT","OTHER_POL_CMTE_CONTRIB","POL_PTY_CONTRIB","CVG_END_DT","INDIV_REFUNDS","CMTE_REFUNDS"]
    CN = ["CAND_ID","CAND_NAME","CAND_PTY_AFFILIATION","CAND_ELECTION_YR","CAND_OFFICE_ST","CAND_OFFICE","CAND_OFFICE_DISTRICT","CAND_ICI","CAND_STATUS","CAND_PCC","CAND_ST1","CAND_ST2","CAND_CITY","CAND_ST","CAND_ZIP"]
    weball = {}
    for line in open(fec_bulk("weball", "weball26.txt"), encoding="latin-1"):
        f = dict(zip(W, line.rstrip("\n").split("|"))); weball[f["CAND_ID"]] = f
    cn = {}
    for line in open(fec_bulk("cn", "cn.txt"), encoding="latin-1"):
        f = dict(zip(CN, line.rstrip("\n").split("|"))); cn[f["CAND_ID"]] = f
    cm = {}
    for line in open(fec_bulk("cm", "cm.txt"), encoding="latin-1"):
        f = line.rstrip("\n").split("|"); cm[f[0]] = {"name": f[1], "type": f[9] if len(f) > 9 else "", "org": f[13] if len(f) > 13 else ""}
    pacs = defaultdict(lambda: defaultdict(float))
    for line in open(fec_bulk("pas2", "itpas2.txt"), encoding="latin-1"):
        f = line.rstrip("\n").split("|")
        if len(f) < 21 or f[5] not in ("24K", "24Z") or not f[16] or f[19] == "X": continue
        pacs[f[16]][f[0]] += money(f[14])
        if f[0] in DEFENSE_IDS: DEFENSE_RCPT[f[16]].add(f[15])
    meta["sources"]["fec"] = {"name": "Federal Election Commission bulk data, 2025-2026 cycle (candidate summary, candidate & committee master, committee-to-candidate contributions)",
        "url": "https://www.fec.gov/data/browse-data/?tab=bulk-data", "retrieved": meta["built_at"][:10],
        "coverage_through": latest_cvg(weball)}
    log(len(weball), "FEC candidate summaries,", len(cn), "candidates,", len(pacs), "with committee contributions")
    return weball, cn, cm, pacs

def committee_to_candidates(cn):
    """Authorized (P/A) committee -> candidate ids, from ccl + each candidate's principal committee."""
    m = defaultdict(set)
    for line in open(fec_bulk("ccl", "ccl.txt"), encoding="latin-1"):
        f = line.rstrip("\n").split("|")
        if len(f) >= 6 and f[5] in ("P", "A") and f[0][:1] in ("H", "S"): m[f[3]].add(f[0])
    for c in cn.values():
        if c.get("CAND_PCC") and c["CAND_ID"][:1] in ("H", "S"): m[c["CAND_PCC"]].add(c["CAND_ID"])
    return m

def run_aipac(cn):
    raw = aipac.fetch(os.path.join(ROOT, "cache"), FEC_KEY, interval=float(os.environ.get("AIPAC_CALL_INTERVAL", FEC_INTERVAL)),
                      max_calls=int(os.environ.get("AIPAC_MAX_CALLS", "800")), log=log)
    agg = aipac.aggregate(raw, committee_to_candidates(cn)) if raw else {}
    meta["sources"]["aipac"] = {"name": "FEC API: AIPAC PAC (C00797670) Schedule B disbursements and United Democracy Project (C00799031) Schedule E independent expenditures, 2025-26",
        "url": "https://www.fec.gov/data/committee/C00797670/?cycle=2026", "status": "ok" if raw else "unavailable",
        "retrieved": raw["fetched"] if raw else None, "schedule_b_rows": len(raw["schedule_b"]) if raw else 0,
        "schedule_e_rows": len(raw["schedule_e"]) if raw else 0}
    if not raw: meta["warnings"].append("AIPAC-related FEC data unavailable this build")
    return agg, (raw["fetched"] if raw else None)

DEFENSE = json.load(open(os.path.join(ROOT, "config", "defense_pacs.json")))
DEFENSE_IDS = {c["committee_id"]: c["company"] for c in DEFENSE["companies"]}
DEFENSE_RCPT = defaultdict(set)

def defense_for(cand_ids, pacs):
    """Direct 2025-26 contributions (24K/24Z, FEC bulk pas2) from the listed defense-contractor PACs."""
    by = defaultdict(float); rc = set()
    for c in cand_ids:
        for cm_id, amt in pacs.get(c, {}).items():
            if cm_id in DEFENSE_IDS: by[cm_id] += amt
        rc |= DEFENSE_RCPT.get(c, set())
    items = sorted(({"company": DEFENSE_IDS[k], "committee_id": k, "total": round(v, 2)} for k, v in by.items() if v), key=lambda x: -x["total"])
    url = ("https://www.fec.gov/data/disbursements/?two_year_transaction_period=2026" + "".join(f"&committee_id={k}" for k in sorted(by))
           + "".join(f"&recipient_committee_id={r}" for r in sorted(x for x in rc if x))) if items else \
          "https://www.fec.gov/data/disbursements/?two_year_transaction_period=2026" + "".join(f"&committee_id={k}" for k in sorted(DEFENSE_IDS))
    return {"status": "ok", "cycle": "2025-26", "total": round(sum(x["total"] for x in items), 2), "by_company": items, "url": url}

def finance_for(cid, weball, cn, cm, pacs):
    w = weball.get(cid); c = cn.get(cid, {})
    out = {"fec_id": cid, "fec_url": f"https://www.fec.gov/data/candidate/{cid}/?cycle={CYCLE}",
           "principal_committee": c.get("CAND_PCC") or None, "available": bool(w)}
    if w:
        out["totals"] = {"receipts": money(w["TTL_RECEIPTS"]), "individual": money(w["TTL_INDIV_CONTRIB"]),
            "pacs_other_committees": money(w["OTHER_POL_CMTE_CONTRIB"]), "party": money(w["POL_PTY_CONTRIB"]),
            "candidate_self": round(money(w["CAND_CONTRIB"]) + money(w["CAND_LOANS"]), 2),
            "disbursements": money(w["TTL_DISB"]), "cash_on_hand": money(w["COH_COP"]), "debts": money(w["DEBTS_OWED_BY"]),
            "coverage_end": w["CVG_END_DT"]}
    tops = sorted(pacs.get(cid, {}).items(), key=lambda kv: -kv[1])[:10]
    out["top_committees"] = [{"id": k, "name": cm.get(k, {}).get("name") or k, "connected_org": cm.get(k, {}).get("org") or "", "total": round(v, 2),
                              "url": f"https://www.fec.gov/data/committee/{k}/"} for k, v in tops]
    return out

# ------------------------------------------------------- FEC API (employers)
def fec_employers(committees_in_priority_order):
    cache = json.load(open(EMP_CACHE)) if os.path.exists(EMP_CACHE) else {}
    today = dt.date.today()
    def age(c):
        e = cache.get(c); return 10**6 if not e else (today - dt.date.fromisoformat(e["fetched"])).days
    seen = set(); order = []
    for c in committees_in_priority_order:
        if c and c not in seen: seen.add(c); order.append(c)
    todo = [c for c in order if age(c) >= 7]
    # keep priority for never-fetched, then stalest first
    todo = [c for c in todo if c not in cache] + sorted([c for c in todo if c in cache], key=lambda c: -age(c))
    calls = 0; stopped = None
    for c in todo:
        if calls >= FEC_MAX_CALLS: stopped = "call budget reached"; break
        url = "https://api.open.fec.gov/v1/schedules/schedule_a/by_employer/"
        try:
            r = S.get(url, params={"api_key": FEC_KEY, "committee_id": c, "cycle": CYCLE, "sort": "-total", "per_page": 40}, timeout=60)
        except requests.RequestException as e:
            stopped = f"network error {e}"; break
        calls += 1
        if r.status_code == 429: stopped = "rate limited (HTTP 429)"; break
        if r.status_code != 200: stopped = f"HTTP {r.status_code}"; break
        items = [{"employer": x.get("employer"), "total": x.get("total"), "count": x.get("count")} for x in r.json().get("results", [])]
        cache[c] = {"fetched": today.isoformat(), "items": items}
        rem = r.headers.get("X-RateLimit-Remaining")
        if rem is not None and int(rem) <= 0: stopped = "rate limit exhausted"; break
        time.sleep(FEC_INTERVAL)
    os.makedirs(os.path.dirname(EMP_CACHE), exist_ok=True)
    json.dump(cache, open(EMP_CACHE, "w"))
    have = sum(1 for c in order if c in cache)
    meta["sources"]["fec_api"] = {"name": "FEC API schedule_a/by_employer (top employers of individual donors)", "url": "https://api.open.fec.gov/developers/",
        "calls_this_build": calls, "stopped_reason": stopped, "committees_covered": have, "committees_total": len(order), "key": "DEMO_KEY" if DEMO else "personal key"}
    log(f"FEC API: {calls} calls, coverage {have}/{len(order)}, stop: {stopped}")
    return cache

def _emp_key(name):
    k = re.sub(r"[^A-Z0-9 ]", " ", (name or "").upper().replace("&", " AND "))
    toks = [t for t in k.split() if t not in ("LLP", "LLC", "INC", "PC", "P", "C", "CORP", "CORPORATION", "CO", "LTD", "THE", "PLLC", "LP", "L")]
    return " ".join(toks)

def clean_employers(items):
    merged = {}
    for x in items:
        nm = (x.get("employer") or "").strip()
        if nm.upper().rstrip(".") in NON_EMPLOYERS or not _emp_key(nm): continue
        k = _emp_key(nm); e = merged.setdefault(k, {"employer": nm, "total": 0.0, "count": 0, "_best": -1})
        e["total"] += x.get("total") or 0; e["count"] += x.get("count") or 0
        if (x.get("total") or 0) > e["_best"]: e["_best"] = x.get("total") or 0; e["employer"] = nm
    out = sorted(merged.values(), key=lambda e: -e["total"])[:10]
    return [{"employer": e["employer"], "total": round(e["total"], 2), "count": e["count"]} for e in out]

def attach_employers(fin, cache):
    c = fin.get("principal_committee"); e = cache.get(c) if c else None
    fin["top_employers"] = {"status": "ok", "fetched": e["fetched"], "items": clean_employers(e["items"])} if e else {"status": "unavailable"}

# ------------------------------------------------------------------- main
def main():
    os.makedirs(RAW, exist_ok=True)
    if os.path.exists(SITE): shutil.rmtree(SITE)
    shutil.copytree(os.path.join(ROOT, "static"), SITE)
    os.makedirs(OUT, exist_ok=True)

    members = load_legislators()
    zips, cd120 = build_zips()
    try: hv = build_house_votes()
    except Exception as e: hv = None; meta["warnings"].append(f"House votes unavailable: {e}"); log("House votes FAILED", e)
    try: sv = build_senate_votes()
    except Exception as e: sv = None; meta["warnings"].append(f"Senate votes unavailable: {e}"); log("Senate votes FAILED", e)
    try: weball, cn, cm, pacs = load_fec(); fec_ok = True
    except Exception as e: fec_ok = False; meta["warnings"].append(f"FEC data unavailable: {e}"); log("FEC FAILED", e)

    # pick each member's FEC candidate id for their current office
    for m in members.values():
        pref = "S" if m["chamber"] == "senate" else "H"
        ids = [i for i in m["fec_ids"] if i.startswith(pref)] or m["fec_ids"]
        if fec_ok:
            ranked = sorted(ids, key=lambda i: (i in weball, money(weball.get(i, {}).get("TTL_RECEIPTS")), cn.get(i, {}).get("CAND_ELECTION_YR", "")), reverse=True)
            m["fec_id"] = ranked[0] if ranked else None
        else:
            m["fec_id"] = ids[0] if ids else None

    # races for the 2026 cycle
    senate_race_states = {m["state"] for m in members.values() if m["chamber"] == "senate" and m["term_end"] < "2029-01-01"}
    races = defaultdict(list)
    if fec_ok:
        for c in cn.values():
            if c["CAND_ELECTION_YR"] != str(CYCLE) or c["CAND_OFFICE"] not in ("H", "S"): continue
            st = c["CAND_OFFICE_ST"]
            if c["CAND_OFFICE"] == "S":
                if st not in senate_race_states: continue
                key = f"{st}-S"
            else:
                key = f"{st}-{(c['CAND_OFFICE_DISTRICT'] or '00').zfill(2)}"
            races[key].append(c["CAND_ID"])

    # FEC API priority: seats for PRIORITY_ZIPS, then incumbents, then candidates by receipts
    if fec_ok:
        prio = []
        for z in PRIORITY_ZIPS:
            for st, cd, *_ in zips.get(z, []):
                keys = [f"{st}-S", f"{st}-{cd}"] + [f'{x["state"]}-{x["district"]}' for x in cd120["zips"].get(z, [])]
                for m in members.values():
                    if m["state"] == st and (m["chamber"] == "senate" or str(m["district"]).zfill(2) == cd):
                        prio.append(cn.get(m["fec_id"], {}).get("CAND_PCC"))
                for k in keys:
                    for cid in sorted(races.get(k, []), key=lambda i: -money(weball.get(i, {}).get("TTL_RECEIPTS"))):
                        if money(weball.get(cid, {}).get("TTL_RECEIPTS")) > 0: prio.append(cn[cid]["CAND_PCC"])
        prio += [cn.get(m["fec_id"], {}).get("CAND_PCC") for m in members.values()]
        allc = sorted({cid for v in races.values() for cid in v}, key=lambda i: -money(weball.get(i, {}).get("TTL_RECEIPTS")))
        prio += [cn[cid]["CAND_PCC"] for cid in allc if money(weball.get(cid, {}).get("TTL_RECEIPTS")) >= 5000]
        try: aip, aip_date = run_aipac(cn)
        except Exception as e: aip, aip_date = {}, None; meta["warnings"].append(f"AIPAC data unavailable: {e}"); log("AIPAC FAILED", e)
        emp = fec_employers(prio)

    # members
    states = defaultdict(lambda: {"senators": [], "house": {}})
    for bid, m in members.items():
        st = states[m["state"]]
        if m["chamber"] == "senate": st["senators"].append(bid)
        else: st["house"][str(m["district"]).zfill(2)] = bid
        src = hv if m["chamber"] == "house" else sv
        if src is None: m["votes"] = None
        else:
            allv = sorted(src.get(bid, []), key=lambda x: (x["date"], x["roll"]), reverse=True)
            v = allv[:VOTES_PER_MEMBER]
            # also keep every Israel-related vote from the whole Congress (not just the recent window);
            # the frontend lists those first
            v += [dict(x, older=True) for x in allv[VOTES_PER_MEMBER:] if x.get("israel")]
            m["votes"] = v
        if fec_ok and m["fec_id"]:
            m["finance"] = finance_for(m["fec_id"], weball, cn, cm, pacs); attach_employers(m["finance"], emp)
            m["finance"]["aipac"] = aipac.badge_data(m["fec_ids"], aip, aip_date)
            m["finance"]["defense"] = defense_for(m["fec_ids"], pacs)
        else:
            m["finance"] = None
        write_json(f"members/{bid}.json", m)

    fec2bio = {i: b for b, m in members.items() for i in m["fec_ids"]}
    for k, ids in races.items():
        st, d = k.split("-")
        incumbents = []
        if d == "S": incumbents = [b for b in states[st]["senators"] if members[b]["term_end"] < "2029-01-01"]
        elif d in states[st]["house"]: incumbents = [states[st]["house"][d]]
        cands = []
        for cid in ids:
            c = cn[cid]; f = finance_for(cid, weball, cn, cm, pacs); attach_employers(f, emp)
            f["aipac"] = aipac.badge_data([cid], aip, aip_date)
            f["defense"] = defense_for([cid], pacs)
            bio = fec2bio.get(cid)
            cands.append({"fec_id": cid, "name": c["CAND_NAME"], "party": c["CAND_PTY_AFFILIATION"],
                "party_abbr": PARTY_ABBR.get(c["CAND_PTY_AFFILIATION"], c["CAND_PTY_AFFILIATION"]),
                "status": {"I": "Incumbent", "C": "Challenger", "O": "Open seat"}.get(c["CAND_ICI"], "Unknown"),
                "fec_candidate_status": c["CAND_STATUS"], "bioguide": bio, "finance": f})
        cands.sort(key=lambda x: -(x["finance"].get("totals", {}).get("receipts", 0)))
        n_open = sum(1 for c in cands if c["status"] == "Open seat"); n_inc = sum(1 for c in cands if c["status"] == "Incumbent")
        write_json(f"races/{k}.json", {"key": k, "fec_open_seat_signal": n_inc > 0 and n_open > 0, "state": st, "district": d, "cycle": CYCLE, "incumbents": incumbents,
            "candidates": cands})
    meta["race_count"] = len(races)
    for st, v in states.items():
        v["senate_race_2026"] = st in senate_race_states
        v["name"] = STATE_NAMES.get(st, st)
        write_json(f"states/{st}.json", v)
    meta["votes_per_member"] = VOTES_PER_MEMBER
    meta["israel_keywords"] = israel.KEYWORDS
    meta["defense_pacs"] = {"companies": DEFENSE["companies"], "sources": DEFENSE["sources"], "not_included": DEFENSE["not_included"]}
    if fec_ok:
        def flag(a): return a.get("status") == "ok" and (a["direct"] + a["earmarked"] > 0)
        def udpf(a): return a.get("status") == "ok" and (a["udp_support"] > 0 or a["udp_oppose"] > 0)
        allc = [c for k in races for c in json.load(open(os.path.join(OUT, f"races/{k}.json")))["candidates"]]
        mf = [m["finance"] for m in members.values() if m.get("finance")]; cf = [c["finance"] for c in allc]
        meta["flag_counts"] = {"members_total": len(members), "candidates_total": len(allc),
            "members_aipac_pac": sum(flag(f["aipac"]) for f in mf) if aip_date else None,
            "members_udp": sum(udpf(f["aipac"]) for f in mf) if aip_date else None,
            "candidates_aipac_pac": sum(flag(f["aipac"]) for f in cf) if aip_date else None,
            "candidates_udp": sum(udpf(f["aipac"]) for f in cf) if aip_date else None,
            "members_defense": sum(f["defense"]["total"] > 0 for f in mf), "candidates_defense": sum(f["defense"]["total"] > 0 for f in cf)}
    write_json("meta.json", meta)
    log("done ->", SITE)

if __name__ == "__main__":
    main()
