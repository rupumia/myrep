#!/usr/bin/env python3
"""Derive Wisconsin ZCTA -> {state senate, state assembly, county, municipality, school district}
overlaps from Census TIGER/Line 2025 boundaries and 2020 ZCTA cartographic boundaries
(equal-area projection, share = fraction of the ZCTA's land area).
Output: data_src/wi_zcta_geo.json (committed; rerun only if boundaries change)."""
import json, os, sys, requests
import geopandas as gpd, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "cache", "raw", "shp"); os.makedirs(RAW, exist_ok=True)
MIN_SHARE = 0.01
def get(url, name):
    p = os.path.join(RAW, name)
    if not os.path.exists(p):
        r = requests.get(url, timeout=600); r.raise_for_status(); open(p, "wb").write(r.content)
    return p
T = "https://www2.census.gov/geo/tiger/TIGER2025/"
layers = {
  "sldu": (T + "SLDU/tl_2025_55_sldu.zip", "wi_sldu.zip", "NAMELSAD"),
  "sldl": (T + "SLDL/tl_2025_55_sldl.zip", "wi_sldl.zip", "NAMELSAD"),
  "county": (T + "COUNTY/tl_2025_us_county.zip", "us_county.zip", "NAMELSAD"),
  "muni": (T + "COUSUB/tl_2025_55_cousub.zip", "wi_cousub.zip", "NAMELSAD"),
  "unsd": (T + "UNSD/tl_2025_55_unsd.zip", "wi_unsd.zip", "NAME"),
  "elsd": (T + "ELSD/tl_2025_55_elsd.zip", "wi_elsd.zip", "NAME"),
  "scsd": (T + "SCSD/tl_2025_55_scsd.zip", "wi_scsd.zip", "NAME"),
}
z = gpd.read_file(get("https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_zcta520_500k.zip", "zcta_500k.zip"))
z = z[z.ZCTA5CE20.str[:2].isin(["53", "54"]) | (z.ZCTA5CE20 == "49947")].to_crs(5070)[["ZCTA5CE20", "geometry"]]
z["zarea"] = z.geometry.area
out = {}
for key, (url, name, col) in layers.items():
    g = gpd.read_file(get(url, name))
    if key == "county":
        g = g[g.STATEFP == "55"]; cname = dict(zip(g.COUNTYFP, g.NAMELSAD))
    if key == "muni":  # town/village/city names repeat across counties: qualify with the county
        g["NAMELSAD"] = g.NAMELSAD + ", " + g.COUNTYFP.map(cname)
    g = g.to_crs(5070)[[col, "geometry"]].rename(columns={col: "nm"})
    ov = gpd.overlay(z, g, how="intersection", keep_geom_type=True)
    ov["share"] = ov.geometry.area / ov["zarea"]
    for zc, grp in ov.groupby("ZCTA5CE20"):
        parts = sorted([(n, round(float(s), 3)) for n, s in zip(grp.nm, grp.share) if s >= MIN_SHARE], key=lambda x: -x[1])
        if parts: out.setdefault(zc, {})[key] = parts
    print(key, len(g), "features", flush=True)
json.dump({"source": "Census TIGER/Line 2025 (SLDU, SLDL, county, county subdivision, school districts) overlaid on 2020 ZCTA cartographic boundaries; share = fraction of ZCTA land area", "zips": out},
          open(os.path.join(ROOT, "data_src", "wi_zcta_geo.json"), "w"), separators=(",", ":"))
print(len(out), "ZCTAs")
