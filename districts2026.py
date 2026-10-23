"""ZIP (ZCTA) -> 2026-election (120th Congress) district mapping for states that redrew.

The Census Bureau has not published a ZCTA-to-120th-district relationship file, so we
derive one: compare TIGER/Line 2025 (119th) and 2026 (120th) district shapes for each
state, and for states whose lines changed, overlay 2020 ZCTA boundaries
(cartographic 1:500k) on the 120th-Congress districts in an equal-area projection.
Result is cached at cache/raw/zcta_cd120.json (delete it to recompute).
"""
import json, os
import requests

MIN_SHARE = 0.005  # ignore overlaps under 0.5% of a ZCTA's land area (generalized-boundary slivers)

def _get(url, dest):
    if not os.path.exists(dest):
        r = requests.get(url, timeout=600); r.raise_for_status()
        open(dest, "wb").write(r.content)
    return dest

def compute(raw_dir, fips_map, log=print):
    out_path = os.path.join(raw_dir, "zcta_cd120.json")
    if os.path.exists(out_path):
        return json.load(open(out_path))
    import geopandas as gpd, pandas as pd
    shp = os.path.join(raw_dir, "shp"); os.makedirs(shp, exist_ok=True)
    changed = []; cd120_frames = []
    for fips, st in sorted(fips_map.items()):
        if st in ("AS", "GU", "MP", "VI"): continue
        try:
            new = gpd.read_file(_get(f"https://www2.census.gov/geo/tiger/TIGER2026/CD/tl_2026_{fips}_cd120.zip", os.path.join(shp, f"cd120_{fips}.zip")))
            old = gpd.read_file(_get(f"https://www2.census.gov/geo/tiger/TIGER2025/CD/tl_2025_{fips}_cd119.zip", os.path.join(shp, f"cd119_{fips}.zip")))
        except Exception as e:
            log("cd120: could not load", st, e); continue
        gcol_new = [c for c in new.columns if c.startswith("GEOID")][0]
        gcol_old = [c for c in old.columns if c.startswith("GEOID")][0]
        new = new.to_crs(5070); old = old.to_crs(5070)
        new["geoid"] = new[gcol_new]; old["geoid"] = old[gcol_old]
        diff = 0.0
        o = old.set_index("geoid").geometry
        for _, row in new.iterrows():
            g_old = o.get(row["geoid"])
            if g_old is None: diff = 1.0; break
            a = row.geometry.area or 1
            diff = max(diff, row.geometry.symmetric_difference(g_old).area / a)
        if diff > 0.001:
            changed.append(st); cd120_frames.append(new[["geoid", "geometry"]])
            log(f"cd120: {st} lines changed (max district area change {diff:.1%})")
    result = {"changed_states": changed, "zips": {}}
    if changed:
        z = gpd.read_file(_get("https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_zcta520_500k.zip", os.path.join(shp, "zcta_500k.zip")))
        z = z.to_crs(5070)[["ZCTA5CE20", "geometry"]]
        z["zarea"] = z.geometry.area
        cds = pd.concat(cd120_frames, ignore_index=True)
        cand = gpd.sjoin(z, cds, predicate="intersects", how="inner")
        ov = gpd.overlay(z[z.ZCTA5CE20.isin(cand.ZCTA5CE20)], cds, how="intersection", keep_geom_type=True)
        ov["share"] = ov.geometry.area / ov["zarea"]
        for zc, grp in ov.groupby("ZCTA5CE20"):
            parts = [(g[:2], g[2:], float(s)) for g, s in zip(grp.geoid, grp.share) if s >= MIN_SHARE]
            if not parts: continue
            result["zips"][zc] = sorted([{"state": fips_map[f], "district": "00" if d == "98" else d, "land_share": round(s, 3)} for f, d, s in parts],
                                        key=lambda x: -x["land_share"])
    json.dump(result, open(out_path, "w"))
    log(f"cd120: {len(changed)} states changed, {len(result['zips'])} ZCTAs mapped to 2026 districts")
    return result
