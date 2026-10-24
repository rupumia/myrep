"""Israel-related roll-call classification.

A roll call is "Israel-related" when any of its text fields matches a keyword in
config/israel_keywords.json (whole word / phrase, case-insensitive). Text fields used:
  * House: Clerk XML vote-question, vote-desc, legis-num; Voteview vote_desc; and, via the
    congress.gov API (same api.data.gov key as the FEC), the bill's official title or the
    amendment's purpose/description plus the amended bill's title.
  * Senate: Voteview vote_question, vote_desc (Senate LIS title / amendment purpose), dtl_desc.

The whole 119th Congress is scanned, not just each member's most recent votes, so older
Israel-related roll calls can be shown at the top of a member's vote list.
congress.gov lookups are cached forever in cache/congress_text.json (titles do not change).
"""
import json, os, re, time
import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(ROOT, "config", "israel_keywords.json")))
KEYWORDS = CFG["keywords"]
def _canon(w):
    """Lower-case and treat any run of spaces/hyphens/dashes as one space ("anti-Semitism" == "anti semitism")."""
    return re.sub(r"[\s\-\u2010-\u2015]+", " ", w).strip().lower()

def _kw_regex(k):
    # Each word of a keyword must appear whole; words may be separated by spaces or hyphens/dashes.
    return r"[\s\-\u2010-\u2015]+".join(re.escape(p) for p in _canon(k).split(" "))

# Whole words: no letter/digit directly before or after. A hyphen is a word boundary on the outside
# (so "United States-Israel" still matches "Israel"); only listed keywords match, so "Semitism"
# alone is never a match, while "anti-Semitism" / "anti Semitism" / "antisemitism" all are.
PATTERN = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(_kw_regex(k) for k in
                     sorted(KEYWORDS, key=len, reverse=True)) + r")(?![A-Za-z0-9])", re.I)
CANON = {}
for _k in KEYWORDS: CANON.setdefault(_canon(_k), _k)
API = "https://api.congress.gov/v3"

def match(*texts):
    """Return the sorted list of distinct keywords found (empty list = not Israel-related)."""
    found = set()
    for t in texts:
        for m in PATTERN.finditer(t or ""):
            found.add(CANON.get(_canon(m.group(1)), m.group(1)))
    return sorted(found)

class CongressText:
    def __init__(self, cache_dir, key, interval=0.8, max_calls=1500, log=print):
        self.path = os.path.join(cache_dir, "congress_text.json")
        self.c = json.load(open(self.path)) if os.path.exists(self.path) else {}
        for k in ("house_votes", "bills", "amendments"): self.c.setdefault(k, {})
        self.key, self.interval, self.max_calls, self.log = key, interval, max_calls, log
        self.calls = 0; self.stopped = None
        self.s = requests.Session(); self.s.headers.update({"User-Agent": "MyRep civic data builder"})

    def _get(self, path, **params):
        if self.stopped or not self.key or self.key == "DEMO_KEY": self.stopped = self.stopped or "no api key"; return None
        if self.calls >= self.max_calls: self.stopped = "call budget reached"; return None
        for attempt in range(3):
            try:
                r = self.s.get(f"{API}{path}", params=dict(params, api_key=self.key, format="json"), timeout=60)
            except requests.RequestException as e:
                time.sleep(3); continue
            finally:
                self.calls += 1; time.sleep(self.interval)
            if r.status_code == 200: return r.json()
            if r.status_code == 404: return {}
            if r.status_code == 429: self.stopped = "rate limited (HTTP 429)"; return None
            time.sleep(3 * (attempt + 1))
        return None

    def house_vote_list(self, congress, session):
        out = []; off = 0
        while True:
            d = self._get(f"/house-vote/{congress}/{session}", limit=250, offset=off)
            if d is None: return None
            v = d.get("houseRollCallVotes", []); out += v
            if len(v) < 250: return out
            off += 250

    def bill_title(self, btype, num, congress):
        k = f"{congress}-{btype.lower()}{num}"
        if k not in self.c["bills"]:
            d = self._get(f"/bill/{congress}/{btype.lower()}/{num}")
            if d is None: return ""
            self.c["bills"][k] = (d.get("bill") or {}).get("title") or ""
        return self.c["bills"][k]

    def amendment_text(self, atype, num, congress):
        k = f"{congress}-{atype.lower()}{num}"
        if k not in self.c["amendments"]:
            d = self._get(f"/amendment/{congress}/{atype.lower()}/{num}")
            if d is None: return None
            a = d.get("amendment") or {}
            self.c["amendments"][k] = {"purpose": a.get("purpose") or "", "description": a.get("description") or "",
                                       "bill_title": (a.get("amendedBill") or {}).get("title") or ""}
        return self.c["amendments"][k]

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        json.dump(self.c, open(self.path, "w"))

def house_roll_text(ct, congress, first_year, log=print):
    """{(year, roll): {"title": str, "texts": [..]}} for every House roll call of the Congress, from congress.gov."""
    out = {}
    for session in (1, 2):
        lst = ct.house_vote_list(congress, session)
        key = f"{congress}-{session}"
        if lst is None:
            lst = ct.c["house_votes"].get(key, [])
            log(f"israel: house-vote list {key} unavailable, using cache ({len(lst)})")
        else:
            ct.c["house_votes"][key] = [{k: x.get(k) for k in ("rollCallNumber", "legislationType", "legislationNumber", "amendmentType", "amendmentNumber")} for x in lst]
            lst = ct.c["house_votes"][key]
        year = first_year + session - 1
        for x in lst:
            texts = []; title = ""
            if x.get("amendmentType") and x.get("amendmentNumber"):
                a = ct.amendment_text(x["amendmentType"], x["amendmentNumber"], congress)
                if a: texts += [a["purpose"], a["description"], a["bill_title"]]; title = a["purpose"] or a["description"]
            elif x.get("legislationType") and x.get("legislationNumber"):
                t = ct.bill_title(x["legislationType"], x["legislationNumber"], congress)
                if t: texts.append(t); title = t
            out[(year, int(x["rollCallNumber"]))] = {"title": title, "texts": texts}
    ct.save()
    return out
