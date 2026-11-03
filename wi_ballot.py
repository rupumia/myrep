"""Wisconsin "On your ballot" data for the Nov 3, 2026 general election.

Candidates and questions come from the Wisconsin Elections Commission's official lists (snapshot in
data_src/wi_contests_2026.json, made by scripts/wi_ballot_snapshot.py). ZIP -> district/county/municipality/
school-district overlaps come from data_src/wi_zcta_geo.json (scripts/wi_zcta_geo.py, Census TIGER/Line).
Writes site/data/ballot/WI.json. Nothing here is invented: every contest is a row in the WEC list.
"""
import json, os, re

ROOT = os.path.dirname(os.path.abspath(__file__))
# WEC district name -> Census school-district name where the two lists spell the same district differently
SCHOOL_ALIAS = {"Minocqua J1 School District": "Minocqua Joint No. 1 School District", "Twin Lakes #4 School District": "Twin Lakes No. 4 School District",
    "Brillion Public School District": "Brillion School District", "Middleton-Cross Plains Area School District": "Middleton-Cross Plains School District",
    "Oconto Unified School District": "Oconto School District", "Fox Point J2 School District": "Fox Point Joint No. 2 School District",
    "Green Bay Area Public School District": "Green Bay Area School District", "Geneva J4 School District": "Geneva Joint No. 4 School District",
    "Whitewater Unified School District": "Whitewater School District"}
MIN_LOCAL = 0.03   # ignore sliver overlaps for referendum/municipal matches
PARTY = {"Republican": "R", "Democratic": "D", "Independent": "I"}

def _norm(s): return re.sub(r"[^a-z0-9]", "", s.lower().replace("&", "and"))

def _cand(c):
    p = c.get("party")
    return {"name": c["name"], "party": p, "abbr": PARTY.get(p, p)} if p else {"name": c["name"]}

def _contest(c):
    if c["referendum"]:
        return {"office": re.sub(r"\s*-\s*QUESTION\s*\d+$", "", c["contest"], flags=re.I) if c["jurisdiction"] == "STATE OF WISCONSIN" else c["contest"],
                "question": c.get("question")}
    return {"office": c["contest"].title().replace(" Of ", " of ") if c["contest"].isupper() else c["contest"], "candidates": [_cand(x) for x in c["candidates"]]}

def build(write_json, meta, log=print):
    snap = json.load(open(os.path.join(ROOT, "data_src", "wi_contests_2026.json")))
    geo = json.load(open(os.path.join(ROOT, "data_src", "wi_zcta_geo.json")))["zips"]
    statewide, house, senate, assembly, county, local_c = [], {}, {}, {}, {}, {}
    # name indexes from the geo layers, so each contest key is exactly what the ZIP overlaps report
    names = {k: set() for k in ("county", "muni", "unsd", "elsd", "scsd")}
    for v in geo.values():
        for k in names:
            for n, _ in v.get(k, []): names[k].add(n)
    county_by_norm = {_norm(n): n for n in names["county"]}
    school_by_norm = {}
    for k in ("unsd", "elsd", "scsd"):
        for n in names[k]: school_by_norm[_norm(re.sub(r"\s+School District$", "", n))] = n
    muni_by_norm = {}
    for n in names["muni"]: muni_by_norm.setdefault(_norm(n), n)
    unmatched = []; multi = {}
    TYPE = {"CITY": "city", "TOWN": "town", "VILLAGE": "village"}
    def muni_key(jur, district):
        m = re.match(r"(CITY|TOWN|VILLAGE) OF (.+?)(?: - (.+))?$", jur, flags=re.I)
        if not m: return None
        t, nm, cty = TYPE[m.group(1).upper()], m.group(2), m.group(3)
        if cty and "MULTIPLE" not in cty.upper():
            return muni_by_norm.get(_norm(f"{nm} {t}, {cty.title().replace('St.', 'St.')}"))
        c = sorted(n for n in names["muni"] if n.lower().startswith(f"{nm.lower()} {t},"))
        if c: multi[f"{nm.title()} {t} (all counties)"] = c  # same city listed once per county in the Census file
        return f"{nm.title()} {t} (all counties)" if c else None
    for c in sorted(snap["contests"], key=lambda c: (c["pos"] or 0)):
        name, jur, dist = c["contest"], c["jurisdiction"], c["district"] or ""
        obj = _contest(c)
        if (jur == "STATE OF WISCONSIN" and c["referendum"]) or name in ("GOVERNOR / LIEUTENANT GOVERNOR", "ATTORNEY GENERAL", "SECRETARY OF STATE", "STATE TREASURER"):
            if name.startswith("GOVERNOR"): obj["office"] = "Governor / Lieutenant Governor (one ticket)"
            statewide.append(obj); continue
        m = re.match(r"REPRESENTATIVE IN CONGRESS DISTRICT (\d+)", name)
        if m: obj["office"] = f"U.S. House · District {m.group(1)}"; house[m.group(1).zfill(2)] = obj; continue
        m = re.match(r"STATE SENATOR DISTRICT (\d+)", name)
        if m: obj["office"] = f"State Senate · District {m.group(1)}"; senate[m.group(1)] = obj; continue
        m = re.match(r"REPRESENTATIVE TO THE ASSEMBLY DISTRICT (\d+)", name)
        if m: obj["office"] = f"State Assembly · District {m.group(1)}"; assembly[m.group(1)] = obj; continue
        # county offices / county-wide questions
        ck = county_by_norm.get(_norm(dist)) or (county_by_norm.get(_norm(jur)) if not c["referendum"] and re.search(r"county$", dist, re.I) else None)
        if ck: county.setdefault(ck, []).append(obj); continue
        # school districts
        d2 = SCHOOL_ALIAS.get(dist, dist)
        sk = school_by_norm.get(_norm(re.sub(r"\s+School District$", "", d2, flags=re.I)))
        if sk: local_c.setdefault(sk, []).append(obj); continue
        mk = muni_key(jur, dist)
        if mk: local_c.setdefault(mk, []).append(obj); continue
        unmatched.append(f"{jur} | {name}")
    zips = {}
    for zc, g in geo.items():
        e = {}
        if g.get("sldu"): e["senate"] = [[re.sub(r"\D", "", n), s] for n, s in g["sldu"]]
        if g.get("sldl"): e["assembly"] = [[re.sub(r"\D", "", n), s] for n, s in g["sldl"]]
        cs = [[n, s] for n, s in g.get("county", []) if n in county and s >= MIN_LOCAL]
        if cs: e["county"] = cs
        acc = {}
        for k in ("muni", "unsd", "elsd", "scsd"):
            for n, s in g.get(k, []):
                key = next((m for m, parts in multi.items() if n in parts), n)
                if key in local_c: acc[key] = round(acc.get(key, 0) + s, 3)
        ls = [[n, s] for n, s in acc.items() if s >= MIN_LOCAL]
        if ls: e["local"] = sorted(ls, key=lambda x: -x[1])
        zips[zc] = e
    # keep only referenced local keys / counties
    used_local = {n for e in zips.values() for n, _ in e.get("local", [])}
    used_cty = {n for e in zips.values() for n, _ in e.get("county", [])}
    out = {"election": snap["election"], "date": snap["date"], "retrieved": snap["retrieved"], "sources": snap["sources"],
           "statewide": statewide, "house": house, "senate": senate, "assembly": assembly,
           "county": {k: v for k, v in county.items() if k in used_cty},
           "local": {k: v for k, v in local_c.items() if k in used_local},
           "zips": zips}
    write_json("ballot/WI.json", out)
    meta["sources"]["ballot_wi"] = {"name": "Wisconsin Elections Commission: official list of contests and candidates for the Nov 3, 2026 general election",
        "url": "https://elections.wi.gov/elections", "retrieved": snap["retrieved"]}
    meta["ballot"] = {"states": ["WI"], "election_date": snap["date"], "unmatched_wi": unmatched}
    log(f"WI ballot: {len(statewide)} statewide, {len(house)} House, {len(senate)} Senate, {len(assembly)} Assembly, "
        f"{sum(len(v) for v in county.values())} county, {sum(len(v) for v in local_c.values())} local contests; unmatched: {unmatched}")
