#!/usr/bin/env python3
"""Download Wisconsin Elections Commission's official lists for the Nov 3, 2026 general election and
save a normalized snapshot at data_src/wi_contests_2026.json (committed; the election is over after Nov 3,
and the WEC website blocks scripted access from some networks such as CI runners).
Sources (WEC, elections.wi.gov):
  All Contests and Candidates_November 3, 2026.xlsx  (file dated Oct 6, 2026)
  Referendum Listing 10.6.26..xlsx"""
import io, json, os, datetime as dt, requests, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B = "https://elections.wi.gov/sites/default/files/documents/"
UA = {"User-Agent": "Mozilla/5.0 (MyRep civic data; public records)"}
def xl(name):
    r = requests.get(B + requests.utils.quote(name), headers=UA, timeout=120); r.raise_for_status()
    return pd.read_excel(io.BytesIO(r.content))
c = xl("All Contests and Candidates_November 3, 2026.xlsx")
rf = xl("Referendum Listing 10.6.26..xlsx")
q = {(str(a).strip()): str(t).strip() for a, t in zip(rf["Referendum Name"], rf["Question"])}
def s(x): return None if pd.isna(x) else str(x).strip()
contests = {}
for _, r in c.iterrows():
    key = (s(r["Jurisdiction"]), s(r["Contest"]), s(r["District"]))
    k = contests.setdefault(key, {"jurisdiction": key[0], "contest": key[1], "district": key[2],
                                  "pos": int(r["Contest Ballot Position"]) if not pd.isna(r["Contest Ballot Position"]) else None,
                                  "referendum": s(r["IsReferendum"]) is not None, "candidates": []})
    if not k["referendum"]:
        k["candidates"].append({"name": s(r["Name On Ballot"]), "party": s(r["Political Party"]),
                                "pos": int(r["Candidate Ballot Position"]) if not pd.isna(r["Candidate Ballot Position"]) else 99})
    else:
        k["question"] = q.get(key[1])
for k in contests.values():
    k["candidates"].sort(key=lambda x: x["pos"])
out = {"election": "2026 General Election", "date": "2026-11-03", "retrieved": dt.date.today().isoformat(),
       "sources": [
         {"name": "WEC: All Contests and Candidates, November 3, 2026 (file dated Oct 6, 2026)", "url": B + "All%20Contests%20and%20Candidates_November%203%2C%202026.xlsx"},
         {"name": "WEC: Referendum Listing (Oct 6, 2026)", "url": B + "Referendum%20Listing%2010.6.26..xlsx"}],
       "contests": sorted(contests.values(), key=lambda k: (k["pos"] or 0, k["contest"]))}
missing = [k["contest"] for k in out["contests"] if k["referendum"] and not k.get("question")]
print(len(out["contests"]), "contests;", sum(k["referendum"] for k in out["contests"]), "referendums; missing question text:", missing)
json.dump(out, open(os.path.join(ROOT, "data_src", "wi_contests_2026.json"), "w"), indent=0)
