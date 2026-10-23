"""AIPAC-related FEC money, 2025-26 cycle only.

Committees (verified on fec.gov / api.open.fec.gov):
  C00797670  AMERICAN ISRAEL PUBLIC AFFAIRS COMMITTEE POLITICAL ACTION COMMITTEE ("AIPAC PAC"),
             PAC - Qualified, Lobbyist/Registrant PAC, connected org: American Israel Public Affairs Committee
  C00799031  UNITED DEMOCRACY PROJECT ('UDP'), Super PAC (independent expenditure-only)

What we count, per candidate:
  * direct:    AIPAC PAC Schedule B (line 23) contributions to a candidate's authorized committee
  * earmarked: AIPAC PAC Schedule B entries whose memo says "EARMARK OF <donor>" -- individual
               contributions AIPAC PAC collected and forwarded as a conduit (voided/refunded earmarks
               are reported as negative amounts and are netted out)
  * outside spending (never "money received"): UDP Schedule E independent expenditures, split into
               support / oppose. 24/48-hour notices are dropped when the same expenditure (candidate,
               date, amount) also appears on a regular report, to avoid double counting.

We query by the conduit/spender committee (one paginated pass, ~400 calls for AIPAC PAC's ~40k
Schedule B rows) instead of per candidate. FEC bulk files (pas2/oth) were checked and are missing
most of AIPAC PAC's 2025-26 reports, so the API is used.
"""
import json, os, time, datetime as dt
from collections import defaultdict
import requests

AIPAC_PAC = "C00797670"
UDP = "C00799031"
CYCLE = 2026
API = "https://api.open.fec.gov/v1"

def _get(session, path, params, key, interval, log):
    for attempt in range(6):
        # FEC's CDN caches 5xx (gateway timeout) responses per URL, so a retry must use a new URL:
        # shrink per_page a little (keyset pagination is unaffected by page size)
        p = dict(params, api_key=key)
        if attempt and "per_page" in p: p["per_page"] = int(p["per_page"]) - attempt
        r = session.get(f"{API}{path}", params=p, timeout=90)
        if r.status_code == 429:
            log("aipac: rate limited, waiting 65s"); time.sleep(65); continue
        if r.status_code >= 500:
            log(f"aipac: HTTP {r.status_code} on {path}, retrying"); time.sleep(5 * (attempt + 1)); continue
        r.raise_for_status(); time.sleep(interval)
        return r.json()
    raise RuntimeError(f"FEC API failed repeatedly for {path}")

def _paginate(session, path, params, key, interval, log, max_calls):
    rows, calls, p = [], 0, dict(params, per_page=100)
    while True:
        if calls >= max_calls: raise RuntimeError("AIPAC call budget exhausted before finishing")
        j = _get(session, path, p, key, interval, log); calls += 1
        res = j.get("results", []); rows += res
        li = j["pagination"].get("last_indexes"); total = j["pagination"].get("count", 0)
        if calls % 10 == 0: log(f"aipac: {path} {params.get('min_date', '')} {len(rows)}/{total}")
        if not res or not li or len(rows) >= total: return rows, calls
        p.update(li)

def _months(cycle):
    out = []
    for y in (cycle - 1, cycle):
        for m in range(1, 13):
            start = dt.date(y, m, 1); end = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1))
            out.append((start.isoformat(), end.isoformat()))
    return out

def _count(session, path, params, key, interval, log):
    j = _get(session, path, dict(params, per_page=1), key, interval, log)
    return j["pagination"]["count"]

def fetch(cache_dir, key, interval=2.5, max_calls=900, max_age_days=6, workers=3, log=print):
    """Returns cached/fresh raw data or None. Partial pulls are never used: row counts must match FEC's totals."""
    from concurrent.futures import ThreadPoolExecutor
    path = os.path.join(cache_dir, f"aipac_{CYCLE}.json")
    old = json.load(open(path)) if os.path.exists(path) else None
    if old and (dt.date.today() - dt.date.fromisoformat(old["fetched"])).days < max_age_days:
        return old
    if key == "DEMO_KEY":
        log("aipac: DEMO_KEY can't page ~400 calls; using cache only"); return old
    s = requests.Session()
    base_b = {"committee_id": AIPAC_PAC, "two_year_transaction_period": CYCLE, "sort": "disbursement_date"}
    try:
        total_b = _count(s, "/schedules/schedule_b/", base_b, key, interval, log)
        # monthly windows fetched in parallel (latency-bound; ~7s per page), keyset-paginated inside each window
        per = max_calls
        def win(w):
            return _paginate(requests.Session(), "/schedules/schedule_b/", dict(base_b, min_date=w[0], max_date=w[1]), key, interval, log, per)
        with ThreadPoolExecutor(workers) as ex:
            parts = list(ex.map(win, _months(CYCLE)))
        sb = [r for rows, _ in parts for r in rows]; c1 = sum(c for _, c in parts) + 1
        # undated rows (if any) are not in a monthly window
        if len({x["sub_id"] for x in sb}) < total_b:
            und, cu = _paginate(s, "/schedules/schedule_b/", dict(base_b, sort_null_only="true"), key, interval, log, 20)
            sb += und; c1 += cu
        n_b = len({x["sub_id"] for x in sb})
        if n_b < total_b: raise RuntimeError(f"AIPAC PAC schedule_b incomplete: {n_b} of {total_b} rows")
        se, c2 = _paginate(s, "/schedules/schedule_e/", {"committee_id": UDP, "cycle": CYCLE, "most_recent": "true",
                                                          "sort": "expenditure_date"}, key, interval, log, 50)
    except Exception as e:
        log("aipac: fetch failed:", e); return old
    keep_b = ("recipient_committee_id", "candidate_id", "disbursement_amount", "disbursement_date", "memo_text", "memo_code",
              "line_number", "sub_id", "transaction_id", "report_year", "report_type", "file_number")
    keep_e = ("candidate_id", "candidate_name", "support_oppose_indicator", "expenditure_amount", "expenditure_date",
              "is_notice", "filing_form", "memo_code", "sub_id", "transaction_id")
    data = {"fetched": dt.date.today().isoformat(), "calls": c1 + c2,
            "schedule_b": [{k: x.get(k) for k in keep_b} for x in sb],
            "schedule_e": [{k: x.get(k) for k in keep_e} for x in se]}
    json.dump(data, open(path, "w"))
    log(f"aipac: fetched {len(sb)} AIPAC PAC disbursements, {len(se)} UDP expenditures in {c1 + c2} calls")
    return data

def aggregate(data, cmte2cands):
    """-> {cand_id: {...}} using committee->candidate linkage (authorized committees)."""
    out = defaultdict(lambda: {"direct": 0.0, "earmarked": 0.0, "udp_support": 0.0, "udp_oppose": 0.0,
                               "recipient_committees": set()})
    if not data: return {}
    seen = set()
    for x in data["schedule_b"]:
        if x["sub_id"] in seen: continue
        seen.add(x["sub_id"])
        if (x.get("memo_code") or "") == "X": continue
        cands = cmte2cands.get(x.get("recipient_committee_id") or "")
        if not cands:
            continue  # party committees, PACs etc. -- not a candidate's campaign
        cid = x.get("candidate_id") if x.get("candidate_id") in cands else sorted(cands)[0]
        amt = float(x.get("disbursement_amount") or 0)
        kind = "earmarked" if "EARMARK" in (x.get("memo_text") or "").upper() else "direct"
        out[cid][kind] += amt; out[cid]["recipient_committees"].add(x["recipient_committee_id"])
    regular = {(x["candidate_id"], x["expenditure_date"], round(float(x["expenditure_amount"] or 0), 2))
               for x in data["schedule_e"] if not x.get("is_notice")}
    seen = set()
    for x in data["schedule_e"]:
        if x["sub_id"] in seen or not x.get("candidate_id") or (x.get("memo_code") or "") == "X": continue
        seen.add(x["sub_id"])
        if x.get("is_notice") and (x["candidate_id"], x["expenditure_date"], round(float(x["expenditure_amount"] or 0), 2)) in regular:
            continue
        k = "udp_support" if x.get("support_oppose_indicator") == "S" else "udp_oppose" if x.get("support_oppose_indicator") == "O" else None
        if k: out[x["candidate_id"]][k] += float(x["expenditure_amount"] or 0)
    res = {}
    for cid, v in out.items():
        v = {k: (round(val, 2) if isinstance(val, float) else sorted(val)) for k, val in v.items()}
        res[cid] = v
    return res

def badge_data(cand_ids, agg, fetched):
    """Combine a person's FEC candidate ids into one record for the site."""
    if fetched is None: return {"status": "unavailable"}
    d = {"direct": 0.0, "earmarked": 0.0, "udp_support": 0.0, "udp_oppose": 0.0}; cmtes = []
    for c in cand_ids:
        a = agg.get(c)
        if not a: continue
        for k in d: d[k] += a[k]
        cmtes += a["recipient_committees"]
    d = {k: round(v, 2) for k, v in d.items()}
    d.update(status="ok", cycle="2025-26", fetched=fetched,
             pac_url=(f"https://www.fec.gov/data/disbursements/?committee_id={AIPAC_PAC}&two_year_transaction_period={CYCLE}"
                      + "".join(f"&recipient_committee_id={c}" for c in sorted(set(cmtes)))) if cmtes else
                     f"https://www.fec.gov/data/committee/{AIPAC_PAC}/?cycle={CYCLE}",
             udp_url=f"https://www.fec.gov/data/independent-expenditures/?committee_id={UDP}&cycle={CYCLE}"
                     + "".join(f"&candidate_id={c}" for c in cand_ids))
    return d
