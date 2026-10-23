# MyRep: how your members of Congress vote, and who funds them

Type a 5-digit ZIP code and see:

* **Your members of Congress**: both senators and your House member. If the ZIP crosses district lines, every possible House member is shown along with the approximate share of the ZIP in each district.
* **Recent roll-call votes**: the 30 most recent votes for each member, with Yea/Nay/Not Voting, the result, a link to the official roll call, and a link to the bill on congress.gov. **Israel-related votes** from anywhere in the current Congress are added and listed first (see below).
* **Campaign money (FEC, 2025–2026)**: total raised, cash on hand, money from individuals, PACs, party committees and self-funding; the top committees and PACs that gave directly; and the top employers of individual donors.
* **2026 races**: everyone registered with the FEC for the seat who has reported raising money, labeled Incumbent / Challenger / Open seat, with the same finance details. Challengers are labeled as having no congressional voting record. For states that redrew their House maps for 2026 (currently AL, CA, FL, LA, MO, NC, OH, TN, TX and UT, detected automatically), the House race shown is for the ZIP's district under the **new** map.

This is a **static site**. `build.py` downloads and precomputes everything into JSON under `site/data/`, so the browser makes no API calls at all. That lets the site be hosted for free on GitHub Pages, Netlify or Cloudflare Pages.

## Run it locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export FEC_API_KEY=your_key       # optional; free at https://api.data.gov/signup. Defaults to DEMO_KEY
.venv/bin/python build.py         # ~2–3 min on a first run (plus FEC API time, see below)
python3 -m http.server 8080 --directory site
# open http://localhost:8080/?zip=10001
```

Useful environment variables:

| Var | Default | Meaning |
|---|---|---|
| `FEC_API_KEY` | `DEMO_KEY` | api.data.gov key used for the FEC employer breakdown |
| `FEC_MAX_CALLS` | 8 (DEMO_KEY) / 900 (own key) | FEC API calls allowed per build |
| `FEC_CALL_INTERVAL` | 2 s / 4 s | pause between FEC calls |
| `PRIORITY_ZIPS` | none | ZIPs whose seats get FEC calls first |
| `VOTES_PER_MEMBER` | 30 | recent votes stored per member |
| `OFFLINE=1` | off | reuse files already downloaded into `cache/raw` |
| `CONGRESS_API_KEY` | `FEC_API_KEY` | api.data.gov key for congress.gov bill titles (Israel-related labels) |
| `CONGRESS_CALL_INTERVAL` | 0.8 s | pause between congress.gov calls |

Tests: `.venv/bin/pip install playwright` and then `.venv/bin/python scripts/e2e_test.py http://localhost:8080`. This runs headless Chromium at desktop and mobile widths for ZIPs 10001, 94103, 78701, 20878 (split), 82001 (WY at-large), 05401 (VT at-large), 20001 (DC) and an invalid ZIP. It fails on any console error or failed request and writes screenshots to `screenshots/`.

## Data sources (all free, no paid keys)

| Data | Source | Freshness |
|---|---|---|
| Current members, ids, photos | [unitedstates/congress-legislators](https://github.com/unitedstates/congress-legislators), photos from unitedstates.github.io/images | community-maintained, usually updated within days |
| ZIP → current (119th) district | Census [2020 ZCTA ↔ 119th CD relationship file](https://www2.census.gov/geo/docs/maps-data/data/rel2020/cd-sld/) | static |
| ZIP → 2026 (120th) district, redrawn states only | derived: Census 2020 ZCTA cartographic boundaries overlaid on [TIGER/Line 2026 CD120](https://www2.census.gov/geo/tiger/TIGER2026/CD/) | static (see `districts2026.py`) |
| House votes | [House Clerk roll-call XML](https://clerk.house.gov/Votes) | same day |
| Senate votes | [Voteview](https://voteview.com/data) Senate roll calls/votes (senate.gov blocks automated downloads from many servers) | usually days behind senate.gov |
| Finance totals, PAC/committee contributions, candidate lists | [FEC bulk data](https://www.fec.gov/data/browse-data/?tab=bulk-data) for 2026: `weball`, `cn`, `cm`, `pas2` | FEC refreshes these daily or weekly |
| Top employers of individual donors | [FEC API](https://api.open.fec.gov/developers/) `schedules/schedule_a/by_employer`, cached in `cache/fec_employers.json` | refreshed when older than 7 days |

The site never fills gaps with made-up data. If a source fails during a build, the affected section says "unavailable" and the About section lists a warning.

## Israel-related votes

`israel.py` labels a roll call **Israel-related** (neutral slate pill; Yea stays green, Nay red) when any of its text fields contains a word or phrase from [`config/israel_keywords.json`](config/israel_keywords.json): Israel, Israeli, Gaza, Hamas, Iron Dome, West Bank, Palestinian(s), UNRWA. Matching is whole-word and case-insensitive. Edit the JSON to change the rule.

- **Text checked.** House: Clerk XML vote question/description/bill number, Voteview's short title, and from the [congress.gov API](https://api.congress.gov/) the bill's official title or, for amendment votes, the amendment's purpose/description and the amended bill's title. Senate: Voteview's vote question and description (the Senate LIS title or amendment purpose).
- **Scope.** Every roll call of the 119th Congress is checked, not just the 30 most recent. Each member's JSON keeps the 30 most recent votes plus every Israel-related vote (`"israel": true`, `"israel_terms": [...]`, older ones marked `"older": true`). The frontend lists Israel-related votes first (newest first, always visible), then the rest in date order.
- **congress.gov** uses the same api.data.gov key as the FEC (`FEC_API_KEY`, or `CONGRESS_API_KEY` if set). Lookups are cached in `cache/congress_text.json`; the first run makes ~800 calls (~12 min), later runs only a handful. Without a key, only the Clerk/Voteview text is used.
- **Limits.** It's a literal title match: it says nothing about which side a vote favors, and it misses votes where Israel isn't named in the title (e.g. omnibus spending bills or procedural "rule" votes).

## AIPAC-related flags (2025–26 cycle)

`aipac.py` adds two separate, neutral labels to members and 2026 candidates. They are never combined.

- **Received AIPAC PAC money: $X (2025-26)** (amber outline). This comes from the Schedule B of AIPAC's PAC, **C00797670** (American Israel Public Affairs Committee Political Action Committee). It includes:
  - direct contributions to the candidate's authorized committees;
  - individual contributions AIPAC PAC forwarded as a conduit (memo "EARMARK OF …"), shown separately and net of voided or refunded earmarks.

  Recipient committees are mapped to candidates with the FEC `ccl` linkage file plus each candidate's principal committee. Gifts to party committees and leadership PACs are not counted.
- **AIPAC-affiliated super PAC spent $X supporting/opposing (2025-26)** (gray dashed outline). This comes from the Schedule E independent expenditures of United Democracy Project, **C00799031**, a super PAC. The data is pulled with `most_recent=true`, and a 24/48-hour notice is dropped when the same candidate, date, and amount also appears on a regular report. This is outside spending, not money the campaign received. The FEC lists no connected organization for UDP; the AIPAC affiliation is publicly reported.

The data is fetched by committee rather than by candidate: about 400 FEC API calls for AIPAC PAC's roughly 40k disbursement rows, plus 4 calls for UDP. It is cached in `cache/aipac_2026.json` and refreshed weekly, and needs a personal `FEC_API_KEY` (with DEMO_KEY only an existing cache is used). A partial pull is never published. If the fetch fails, the previous cache is used or the site shows "unavailable". FEC bulk files (`pas2`, `oth`) were checked and are missing most of AIPAC PAC's 2025–26 reports, so they are not used.

## Weapons-industry flag (2025–26 cycle)

The **Received weapons-industry PAC money: $X (2025-26)** label (stone-gray solid outline) shows direct contributions to a candidate's committees from the corporate PACs listed in [`config/defense_pacs.json`](config/defense_pacs.json). Tapping the label shows the amount from each company.

- **Data:** FEC bulk `pas2` file, transaction types 24K/24Z, excluding memo entries. Voided contributions come through as negative rows and are netted out.
- **Companies:** the five largest DoD contractors by FY2024 obligations (CRS IF10600, SAM.gov data), plus Huntington Ingalls, L3Harris, BAE Systems Inc., Leidos, Textron, and General Atomics.
- **Verification:** each committee ID was checked on api.open.fec.gov.
- **Not included:** employee (individual) donations. The employer data the site already has is only each campaign's top 40 employers, so totals built from it would undercount. Gun-lobby groups are also excluded.

## Deploying publicly (GitHub Pages, updated weekly)

`.github/workflows/weekly.yml` runs every Monday (and on manual dispatch or a push to `main`). It builds the site, caches downloads and FEC results between runs with `actions/cache`, and deploys `site/` to GitHub Pages.

What you need to do:
1. **A GitHub account.** Create a repository (public is free for Pages) and push this folder to it on branch `main`.
2. **A free FEC / api.data.gov key** from https://api.data.gov/signup. In the repo, add it under *Settings → Secrets and variables → Actions → New repository secret* with the name `FEC_API_KEY`. Without it the build still works, but only about 8 campaigns get an employer breakdown per run. With it, a run covers all ~2,500 campaigns in about 2.7 hours, well within the 6-hour job limit.
3. Under *Settings → Pages*, set **Source: GitHub Actions**.
4. Run the workflow once from the *Actions* tab. The URL will be `https://<user>.github.io/<repo>/`.
5. (Optional) Add a custom domain under *Settings → Pages*.

Notes: GitHub pauses scheduled workflows in repos with no activity for 60 days, so re-enable it from the Actions tab if that happens. To use Netlify or Cloudflare Pages instead, run the same build (in their build step or in GitHub Actions) and publish the `site/` directory. Their default build-time limits are shorter, so keep the FEC call budget low there or run the build in GitHub Actions.

## Known limitations

* ZIP codes are approximated with Census ZCTAs. PO-box-only ZIPs aren't covered, and splits are by land area rather than population. Users should confirm with their address at house.gov.
* The 2026 district mapping for redrawn states is computed from generalized (1:500k) boundaries. Overlaps under 0.5% of a ZIP's area are ignored.
* The FEC candidate list includes everyone registered for 2026. It can include people who lost a primary or withdrew, because the FEC doesn't publish primary results in these files.
* "Top committees/PACs" adds up direct contributions (FEC transaction types 24K and 24Z) in the 2026 `pas2` file, which may include amended duplicates. Independent expenditures are not counted as money a candidate "took".
* Employer names are free text typed by donors. Obvious variants are merged, but "Wachtell Lipton" and "Wachtell Lipton Rosen & Katz" can still show up separately.
* Senate votes come from Voteview, which can lag senate.gov.
* Finance totals cover the 2025–2026 two-year period only. A senator's full six-year cycle isn't summed.
