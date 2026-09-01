#!/usr/bin/env python3
"""
OHGO -> per-pad road alerts for the Titan Haul Routes site.

Strategy (tuned for low noise): only flag a pad when an OHGO event is
(1) physically near the pad AND (2) on one of the pad's LOCAL APPROACH roads
(the last few turns in its route) or a road named in its turn list. Interstates
are ignored unless the event is right on top of the pad, because a lane closure
on a 40-mile interstate approach rarely strands a water truck.

Runs from a GitHub Action. Needs env var OHGO_API_KEY.
"""
import os, re, json, math, sys, urllib.request, urllib.parse, datetime

# ---------------- CONSTANTS (tune these) ----------------
OHGO_BASE      = "https://publicapi.ohgo.com/api/v1"
ENDPOINTS      = ["construction", "incidents"]     # slowdowns are transient/interstate; skip for now
PROX_MI        = 6.0     # event must be within this many miles of the pad
INTERSTATE_MI  = 1.5     # an interstate event only counts if basically on top of the pad
APPROACH_STEPS = 3       # how many of the last turns count as the "local approach"
INDEX_PATH     = "index.html"
OUT_PATH       = "alerts.json"
CLOSE_RE       = re.compile(r'clos|detour|blocked|restrict|ramp closed|road closed|lane closed', re.I)
CATEGORY_LABEL = {"construction":"Closure/construction","incidents":"Incident"}

ROUTE_TYPE_RE = re.compile(r'\b(SR|OH|US|I|IR|CR|TR|TWP)\s*-?\s*(\d{1,4})\b', re.I)
NAME_RE = re.compile(r'\b([A-Z][A-Za-z\.]+(?:\s+[A-Z][A-Za-z\.]+){0,3}\s+(?:Rd|Road|Ln|Lane|Ave|Avenue|St|Street|Dr|Drive|Pike|Hwy|Highway|Ridge|Run|Hill|Creek|Hollow|Church))\b')

def norm_route(t, n):
    t=t.upper()
    if t=="OH": t="SR"
    if t=="IR": t="I"
    return (t, n)

def _toks(text):
    routes=set(); names=set()
    for m in ROUTE_TYPE_RE.finditer(text): routes.add(norm_route(m.group(1), m.group(2)))
    for m in NAME_RE.finditer(text):
        nm=re.sub(r'\s+',' ',m.group(1)).strip().lower(); nm=re.sub(r'\broad\b','rd',nm)
        if len(nm)>=6: names.add(nm)   # skip too-short generic names
    return routes, names

def haversine_mi(a_lat,a_lon,b_lat,b_lon):
    R=3958.8; p1,p2=math.radians(a_lat),math.radians(b_lat)
    dp=math.radians(b_lat-a_lat); dl=math.radians(b_lon-a_lon)
    h=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(math.sqrt(h))

def load_pads(path):
    html=open(path,encoding='utf-8').read()
    m=re.search(r'const DATA\s*=\s*(\[.*?\]);', html, re.S) or re.search(r'(\[\{.*\}\]);', html, re.S)
    data=json.loads(m.group(1))
    def normid(s): return re.sub(r'\s+',' ',re.sub(r'[^a-z0-9 ]+',' ',(s or '').lower())).strip().replace(' ','-')
    pads=[]
    for d in data:
        if not (d.get('lat') and d.get('lon')): continue
        seqs=[]
        if d.get('steps'): seqs.append(d['steps'])
        if d.get('segs'):
            for g in d['segs']:
                if g.get('s'): seqs.append(g['s'])
        if not seqs: continue
        # approach routes = last APPROACH_STEPS (numbers matched only here, to avoid interstate noise);
        # local road NAMES matched across the WHOLE route (names are precise, so no noise).
        appr=set(); names=set()
        for s in seqs:
            r,_=_toks(" ".join(s[-APPROACH_STEPS:])); appr|=r
            _,n=_toks(" ".join(s)); names|=n
        if not appr and not names: continue
        pads.append({'id':normid(d['src']+'-'+d['pad']),'pad':d['pad'],'lat':d['lat'],'lon':d['lon'],
                     'appr':appr,'names':names})
    return pads

def ohgo_get(endpoint, key):
    url=OHGO_BASE+"/"+endpoint
    req=urllib.request.Request(url, headers={"Authorization":"APIKEY "+key})
    out=[]
    for _ in range(30):
        with urllib.request.urlopen(req, timeout=30) as r: j=json.load(r)
        rows=j.get('results') or j.get('Results') or []
        out+=rows
        nxt=(j.get('pagination') or {}).get('nextUrl') or (j.get('Pagination') or {}).get('NextUrl')
        if not nxt: break
        req=urllib.request.Request(nxt, headers={"Authorization":"APIKEY "+key})
    return out

def event_fields(ev):
    def g(*ks):
        for k in ks:
            for kk in (k, k[0].upper()+k[1:]):
                if kk in ev and ev[kk] not in (None,""): return ev[kk]
        return ""
    try: lat=float(g('latitude')); lon=float(g('longitude'))
    except: lat=lon=None
    road=str(g('routeName','roadName','route'))
    desc=str(g('description','category')).strip()
    loc=str(g('location','locationDescription')).strip()
    routes=set()
    for m in ROUTE_TYPE_RE.finditer(road): routes.add(norm_route(m.group(1),m.group(2)))
    return {'lat':lat,'lon':lon,'road':road,'desc':desc or loc,'loc':loc,'routes':routes,
            'start':parse_dt(g('startDate','startTime')),'end':parse_dt(g('endDate','endTime')),
            'blob':(road+" "+desc+" "+loc).lower()}

def parse_dt(s):
    if not s: return None
    s=str(s).strip().replace('Z','')
    try: return datetime.datetime.fromisoformat(s).replace(tzinfo=None)
    except: pass
    for f in ('%m/%d/%Y %I:%M:%S %p','%m/%d/%Y %H:%M:%S','%m/%d/%Y','%Y-%m-%d'):
        try: return datetime.datetime.strptime(s,f)
        except: pass
    return None

def match(pads, events, cat):
    now=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    hits={}
    for ev in events:
        e=event_fields(ev)
        if cat=='construction':
            if not CLOSE_RE.search(e['blob']): continue
            if e['end'] and e['end'] < now: continue        # already ended
            if e['start'] and e['start'] > now: continue     # not started yet (currently-active only)
        if e['lat'] is None: continue
        for p in pads:
            dist=haversine_mi(p['lat'],p['lon'],e['lat'],e['lon'])
            if dist>PROX_MI: continue
            matched=False; why=""
            # 1) local road NAME match anywhere in the route (most precise)
            for nm in p['names']:
                if nm in e['blob']: matched=True; why=nm.title(); break
            # 2) approach ROUTE match (non-interstate; interstate only if right on the pad)
            if not matched and e['routes']:
                common=p['appr'] & e['routes']
                nonI=[r for r in common if r[0]!='I']
                if nonI: matched=True; why=nonI[0][0]+'-'+nonI[0][1]
                elif common and dist<=INTERSTATE_MI: matched=True; why=list(common)[0][0]+'-'+list(common)[0][1]
            if matched:
                txt=f"{CATEGORY_LABEL.get(cat,cat)}: {e['desc'] or e['road']}".strip()
                if e['road'] and e['road'].lower() not in txt.lower(): txt+=f" ({e['road']})"
                hits.setdefault(p['id'],[]).append(txt[:240])
    return hits

def main():
    key=os.environ.get("OHGO_API_KEY")
    if not key: print("OHGO_API_KEY not set", file=sys.stderr); sys.exit(1)
    pads=load_pads(INDEX_PATH)
    print(f"pads with approach roads: {len(pads)}")
    allhits={}
    for cat in ENDPOINTS:
        try: evs=ohgo_get(cat,key)
        except Exception as e: print(f"  {cat}: fetch error {e}", file=sys.stderr); continue
        for s in evs:   # probe: does OHGO carry the Pipe Creek / Homco closure?
            b=(str(s.get('routeName',''))+" "+str(s.get('description',''))+" "+str(s.get('location',''))).lower()
            if 'pipe creek' in b or 'homco' in b:
                print(f"  >>> OHGO HAS IT: {str(s.get('description',''))[:120]}")
        h=match(pads,evs,cat)
        print(f"  {cat}: {len(evs)} events -> {sum(len(v) for v in h.values())} matches on {len(h)} pads")
        for k,v in h.items(): allhits.setdefault(k,[]).extend(v)
    for k in allhits: allhits[k]=list(dict.fromkeys(allhits[k]))[:4]
    out={"updated":datetime.datetime.now(datetime.timezone.utc).isoformat(),"source":"OHGO (ODOT)","alerts":allhits}
    json.dump(out,open(OUT_PATH,'w'))
    print(f"wrote {OUT_PATH}: {len(allhits)} pads flagged")
    if allhits:
        for pid,txts in list(allhits.items())[:8]:
            print(f"   FLAGGED {pid}: {txts[0][:90]}")

if __name__=="__main__":
    main()
