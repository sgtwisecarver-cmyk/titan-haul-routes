"""Bridges a loaded water truck (80,000 lb) should watch for -> data/bridges.json for the map.

    python tools/build_bridges.py --nbi <folder with WV25.txt and PA25.txt>

Ohio: ODOT TIMS Bridge Inventory (live ArcGIS service) - NBI 041 open/posted/closed, NBI 070 posting,
      and Ohio item 734 "Percent Legal" (the bridge's load rating as a percent of Ohio legal loads).
WV / PA: the FHWA National Bridge Inventory delimited files (https://www.fhwa.dot.gov/bridge/nbi/<year>/delimited/),
      NBI 041 and NBI 070 (how far the rating falls below legal loads).
Only bridges that carry a road, inside the area our pads cover (+ ~20 miles), and that are closed, posted,
or rated under legal loads are kept. The weight bands are estimates from the rating: the posted sign rules.
Bridge data changes a few times a year; re-run when ODOT/FHWA publish a new year.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import pathlib
import re
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
TIMS = "https://tims.dot.state.oh.us/ags/rest/services/Assets/Bridge_Inventory/MapServer/0/query"
ROAD_SERVICE = {"1", "4", "5", "6", "7", "8"}          # NBI 042A: the structure carries highway traffic
POSTED = {"P", "R"}
# severity: 3 closed, 2 posted or under ~40,000 lb, 1 ~40,000-65,000 lb, 0 ~66,000-79,000 lb


def pads_bbox(pad=0.3):
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    import pads   # data/pads/*.json (v30.6)
    data = pads.load_cards(str(ROOT))
    la = [d["lat"] for d in data if d.get("lat")]
    lo = [d["lon"] for d in data if d.get("lon")]
    return min(la) - pad, max(la) + pad, min(lo) - pad, max(lo) + pad


def clean(s):
    return re.sub(r"\s+", " ", (s or "").strip().strip("'").strip()).title()


def ohio(bb):
    where = "GEN_OPR_STATUS<>'A' OR (LOAD_RAT_PCT>0 AND LOAD_RAT_PCT<100) OR BRG_POSTING IN ('0','1','2','3','4')"
    q = urllib.parse.urlencode({
        "where": where, "returnGeometry": "false", "resultRecordCount": "20000", "f": "json",
        "outFields": "SFN,STR_LOC_CARRIED,INVENT_FEAT,STR_LOC,LATITUDE_DD,LONGITUDE_DD,GEN_OPR_STATUS,"
                     "BRG_POSTING,LOAD_RAT_PCT,TYPE_SERV1_CD,INSP_DT"})
    with urllib.request.urlopen(TIMS + "?" + q, timeout=120) as r:
        j = json.load(r)
    if j.get("exceededTransferLimit"):
        raise SystemExit("ODOT returned a partial list - page the query")
    out = []
    for f in j["features"]:
        a = f["attributes"]
        lat, lon, st = a["LATITUDE_DD"], a["LONGITUDE_DD"], (a["GEN_OPR_STATUS"] or "").strip()
        if not lat or not lon or not (bb[0] <= lat <= bb[1] and bb[2] <= lon <= bb[3]):
            continue
        if (a["TYPE_SERV1_CD"] or "").strip() not in ROAD_SERVICE or st in ("G", ""):
            continue
        pct = a["LOAD_RAT_PCT"] or 0
        if st == "K":
            sev = 3
        elif st in POSTED or 0 < pct < 50:
            sev = 2
        elif 0 < pct < 82:
            sev = 1
        elif 0 < pct < 100:
            sev = 0
        else:
            post = (a["BRG_POSTING"] or "").strip()
            if post not in ("0", "1", "2", "3", "4"):
                continue
            sev = 2 if post in ("0", "1") else 1 if post in ("2", "3") else 0
        insp = dt.datetime.fromtimestamp(a["INSP_DT"] / 1000, dt.UTC).strftime("%Y-%m") if a.get("INSP_DT") else ""
        out.append({"id": "OH-" + a["SFN"].strip(), "s": "OH", "lat": round(lat, 5), "lon": round(lon, 5), "v": sev,
                    "st": st, "pct": pct or None, "on": clean(a["STR_LOC_CARRIED"]), "x": clean(a["INVENT_FEAT"]),
                    "loc": clean(a["STR_LOC"]), "insp": insp})
    return out


def dms(v, digits):
    v = (v or "").strip().zfill(digits)
    if not v.strip("0"):
        return None
    d = int(v[:digits - 6]); m = int(v[digits - 6:digits - 4]); s = int(v[digits - 4:]) / 100
    return d + m / 60 + s / 3600


def nbi(path: pathlib.Path, state, bb):
    out = []
    with path.open(encoding="latin-1", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["SERVICE_ON_042A"].strip() not in ROAD_SERVICE:
                continue
            st = r["OPEN_CLOSED_POSTED_041"].strip()
            post = r["POSTING_EVAL_070"].strip()
            if st == "K":
                sev = 3
            elif st in POSTED or post in ("0", "1"):
                sev = 2
            elif post in ("2", "3"):
                sev = 1
            elif post == "4":
                sev = 0
            else:
                continue
            lat, lon = dms(r["LAT_016"], 8), dms(r["LONG_017"], 9)
            if lat is None or lon is None:
                continue
            lon = -lon
            if not (bb[0] <= lat <= bb[1] and bb[2] <= lon <= bb[3]):
                continue
            out.append({"id": state + "-" + r["STRUCTURE_NUMBER_008"].strip(), "s": state, "lat": round(lat, 5),
                        "lon": round(lon, 5), "v": sev, "st": st, "pct": None,
                        "on": clean(r["FACILITY_CARRIED_007"]), "x": clean(r["FEATURES_DESC_006A"]),
                        "loc": clean(r["LOCATION_009"]), "insp": ""})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nbi", help="folder holding the FHWA WV??.txt / PA??.txt files")
    a = ap.parse_args()
    bb = pads_bbox()
    rows = ohio(bb)
    if a.nbi:
        for st in ("WV", "PA"):
            f = sorted(pathlib.Path(a.nbi).glob(st + "??.txt"))
            if f:
                rows += nbi(f[-1], st, bb)
    rows.sort(key=lambda r: -r["v"])
    out = {"generated": dt.datetime.now(dt.UTC).strftime("%Y-%m-%d"),
           "source": "ODOT TIMS Bridge Inventory (Ohio) and FHWA National Bridge Inventory 2025 (WV, PA)",
           "bridges": rows}
    (ROOT / "data" / "bridges.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    from collections import Counter
    print(len(rows), "bridges", dict(Counter((r["s"], r["v"]) for r in rows)))


if __name__ == "__main__":
    main()
