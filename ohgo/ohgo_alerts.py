#!/usr/bin/env python3
"""
OHGO -> alerts.json for the Titan Haul Routes site.   (v4: corridors + traffic + weather + cameras)

Outputs three things into alerts.json:
  alerts    per-pad text alerts (closures / incidents on a pad's route)      -- unchanged behaviour
  padx      per-pad extras: active work zones w/ dates, hazardous road-surface readings, nearest route camera
  corridors interstate corridor boards (I-77 MM 1-101, I-70 MM 164-216): traffic (delays, slowdowns,
            sign travel-time pace), incidents, work zones, weather stations, cameras -- all filtered by MM range

Runs from a GitHub Action (needs env OHGO_API_KEY).  Local test:  python ohgo_alerts.py --fixtures ohgo/fixtures.json
"""
import os, re, json, math, sys, urllib.request, datetime

# ---------------- CONSTANTS (tune these) ----------------
OHGO_BASE      = "https://publicapi.ohgo.com/api/v1"
PROX_MI        = 6.0     # per-pad: event must be within this many miles of the pad
FRAC_SITE_MI   = 1.0      # frac cards inherit alerts from pad cards within this distance (same site)
INTERSTATE_MI  = 1.5     # per-pad: an interstate event only counts if basically on top of the pad
APPROACH_STEPS = 3       # per-pad: last N turns = the "local approach"
WX_MI          = 15.0    # per-pad: how far to look for a weather station
CAM_MI         = 12.0    # per-pad: how far to look for a camera on a route road
INDEX_PATH     = "index.html"
OUT_PATH       = "alerts.json"
CLOSE_RE       = re.compile(r'clos|detour|blocked|restrict|ramp closed|road closed|lane closed', re.I)
CATEGORY_LABEL = {"construction":"Closure/construction","incidents":"Incident"}

# Corridors. mm range + calibration anchors (mile marker -> lat for N-S roads, -> lon for E-W roads),
# taken from ODOT RWIS station names / signs / cameras that carry exact mile markers.
CORRIDORS = [
  {"id":"i77","num":77,"name":"I-77","label":"I-77 · Marietta to Canton (MM 1–101)","mm":[1,101],"axis":"lat",
   "re":re.compile(r'\b(?:I|IR)\s*-?\s*77\b(?!\d)',re.I),
   "cal":[(0.66,39.413),(17.01,39.6286),(36.53,39.8958),(47,40.001),(60.05,40.2204),(83,40.574),(95.11,40.6649),(101,40.7508),(109.63,40.8594),(120.94,40.9973),(150.02,41.3171),(156.64,41.4115)]},
  {"id":"i70","num":70,"name":"I-70","label":"I-70 · Norwich to St. Clairsville (MM 164–216)","mm":[164,216],"axis":"lon",
   "re":re.compile(r'\b(?:I|IR)\s*-?\s*70\b(?!\d)',re.I),
   "cal":[(143.52,-82.2112),(152,-82.0403),(156,-81.9718),(178,-81.545),(198.07,-81.24),(216,-80.8613),(219,-80.76)]},
]
MM_SLOP = 2.0   # miles of tolerance on the corridor ends when MM is estimated from position

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
        if len(nm)>=6: names.add(nm)
    return routes, names

def haversine_mi(a_lat,a_lon,b_lat,b_lon):
    R=3958.8; p1,p2=math.radians(a_lat),math.radians(b_lat)
    dp=math.radians(b_lat-a_lat); dl=math.radians(b_lon-a_lon)
    h=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(math.sqrt(h))

def clean(s): return re.sub(r'\s+',' ',str(s or '')).strip()

# ---------------- pads ----------------
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
        appr=set(); names=set(); allroutes=set()
        for s in seqs:
            r,_=_toks(" ".join(s[-APPROACH_STEPS:])); appr|=r
            r2,n=_toks(" ".join(s)); names|=n; allroutes|=r2
        pads.append({'id':d.get('id') or normid(d['src']+'-'+d['pad']),'pad':d['pad'],'src':d.get('src',''),'lat':d['lat'],'lon':d['lon'],
                     'appr':appr,'names':names,'routes':allroutes,'has_route':bool(seqs)})
    return pads

# ---------------- OHGO fetch ----------------
def ohgo_get(endpoint, key):
    url=OHGO_BASE+"/"+endpoint+("&" if "?" in endpoint else "?")+"page-all=true"
    req=urllib.request.Request(url, headers={"Authorization":"APIKEY "+key})
    with urllib.request.urlopen(req, timeout=60) as r: j=json.load(r)
    return j.get('results') or j.get('Results') or []

def thin(pl, n=8):
    if not pl or len(pl)<=n: return pl
    step=(len(pl)-1)/(n-1); return [pl[round(i*step)] for i in range(n)]

def fetch_all_live(key):
    """Normalise live API rows to the compact fixture shape used by the matcher."""
    fx={}
    inc=ohgo_get("incidents",key)
    fx['incidents']=[{'id':x.get('id'),'lat':x.get('latitude'),'lon':x.get('longitude'),'loc':x.get('location'),'desc':x.get('description'),
                      'cat':x.get('category'),'dir':x.get('direction'),'route':x.get('routeName'),'status':x.get('roadStatus'),
                      'pl':thin((x.get('roadClosureDetails') or {}).get('polyline'))} for x in inc]
    con=ohgo_get("construction",key)
    fx['construction']=[{'id':x.get('id'),'lat':x.get('latitude'),'lon':x.get('longitude'),'loc':x.get('location'),'desc':x.get('description'),
                         'cat':x.get('category'),'dir':x.get('direction'),'route':x.get('routeName'),'status':x.get('status'),
                         'start':x.get('startDate'),'end':x.get('endDate'),'pl':[thin(w.get('polyline')) for w in (x.get('workZones') or [])]} for x in con]
    fx['delays']=[{'id':x.get('id'),'lat':x.get('latitude'),'lon':x.get('longitude'),'loc':x.get('location'),'desc':x.get('description'),'dir':x.get('direction'),
                   'route':x.get('routeName'),'mm0':x.get('startMileMarker'),'mm1':x.get('endMileMarker'),'delay':x.get('delayTime'),'travel':x.get('travelTime'),
                   'cur':x.get('currentAvgSpeed'),'normal':x.get('normalAvgSpeed')} for x in ohgo_get("travel-delays",key)]
    fx['slowdowns']=[{'id':x.get('id'),'lat':x.get('latitude'),'lon':x.get('longitude'),'loc':x.get('location'),'desc':x.get('description'),'dir':x.get('direction'),
                      'route':x.get('routeName'),'cur':x.get('currentMPH'),'normal':x.get('normalMPH')} for x in ohgo_get("dangerous-slowdowns",key)]
    fx['weather']=[{'id':x.get('id'),'lat':x.get('latitude'),'lon':x.get('longitude'),'loc':x.get('location'),'severe':x.get('severe'),'cond':x.get('condition'),
                    'air':x.get('averageAirTemperature'),
                    'atm':[{'t':a.get('airTemperature'),'precip':a.get('precipitation'),'pint':a.get('precipitationintensity'),'vis':a.get('visibility'),
                            'wind':a.get('averageWindSpeed'),'gust':a.get('maximumWindSpeed'),'upd':a.get('lastUpdate')} for a in (x.get('atmosphericSensors') or [])[:1]],
                    'surf':[{'n':s.get('name'),'st':s.get('status'),'t':s.get('surfaceTemperature'),'upd':s.get('lastUpdate')} for s in (x.get('surfaceSensors') or [])]} for x in ohgo_get("weather-sensor-sites",key)]
    fx['cameras']=[{'id':x.get('id'),'lat':x.get('latitude'),'lon':x.get('longitude'),'loc':x.get('location'),
                    'u':((x.get('cameraViews') or [{}])[0]).get('smallUrl'),'d':((x.get('cameraViews') or [{}])[0]).get('direction')} for x in ohgo_get("cameras",key)]
    fx['signs']=[{'id':x.get('id'),'lat':x.get('latitude'),'lon':x.get('longitude'),'loc':x.get('location'),'type':x.get('signTypeName'),'msgs':x.get('messages') or []} for x in ohgo_get("digital-signs",key)]
    return fx

# ---------------- helpers ----------------
def parse_dt(s):
    if not s: return None
    s=str(s).strip().replace('Z','')
    try: return datetime.datetime.fromisoformat(s).replace(tzinfo=None)
    except: pass
    for f in ('%m/%d/%Y %I:%M:%S %p','%m/%d/%Y %H:%M:%S','%m/%d/%Y','%Y-%m-%d'):
        try: return datetime.datetime.strptime(s,f)
        except: pass
    return None

def is_active(ev, now):
    st=parse_dt(ev.get('start')); en=parse_dt(ev.get('end'))
    if en and en<now: return False
    if st and st>now: return False
    return True

def fmt_date(s):
    d=parse_dt(s); return d.strftime('%b %-d') if d else ''

def sane_temp(t):
    try: t=float(t)
    except: return None
    return t if -60<=t<=150 else None

def parse_mm(text, routenum=None):
    """Return (mm_lo, mm_hi) parsed from free text, or (None,None). routenum ties RWIS-style 'IR70 198.07' to the right road."""
    t=text or ''
    m=re.search(r'mile\s*markers?\s+([\d.]+)\s+(?:and|to|-|through)\s+([\d.]+)', t, re.I)
    if m: a,b=float(m.group(1)),float(m.group(2)); return (min(a,b),max(a,b))
    m=re.search(r'\bMM:?\s*([\d.]+)', t, re.I)
    if m: v=float(m.group(1)); return (v,v)
    if routenum:
        m=re.search(r'\b(?:IR|I)\s*-?\s*'+str(routenum)+r'\s+(\d{1,3}\.\d{1,2})\b', t)   # RWIS style "IR70 198.07"
        if m: v=float(m.group(1)); return (v,v)
    return (None,None)

def mm_from_point(cor, lat, lon):
    """Piecewise-linear estimate of mile marker from position along the corridor axis."""
    x = lat if cor['axis']=='lat' else lon
    cal=cor['cal']
    if x<=cal[0][1]: a,b=cal[0],cal[1]
    elif x>=cal[-1][1]: a,b=cal[-2],cal[-1]
    else:
        for a,b in zip(cal,cal[1:]):
            if a[1]<=x<=b[1]: break
    if b[1]==a[1]: return a[0]
    return a[0]+(x-a[1])*(b[0]-a[0])/(b[1]-a[1])

def in_corridor(cor, text, lat, lon):
    """Is this item on the corridor route and inside the MM range? returns (mm_lo, mm_hi) or None."""
    if not cor['re'].search(text or ''): return None
    lo,hi=parse_mm(text, cor.get('num'))
    if lo is None:
        if lat is None or lon is None: return None
        v=mm_from_point(cor,lat,lon); lo=hi=round(v,1); slop=MM_SLOP
    else: slop=0.0
    a,b=cor['mm']
    if hi < a-slop or lo > b+slop: return None
    return (lo,hi)

def dir_short(d):
    d=(d or '').strip()
    m={'northbound':'NB','southbound':'SB','eastbound':'EB','westbound':'WB','n':'NB','s':'SB','e':'EB','w':'WB','both directions':'Both','both':'Both'}
    return m.get(d.lower(), d[:12])

def sign_legs(msg):
    """Parse a travel-time sign into [{to, mi, min, mph}]."""
    t=re.sub(r'\s+',' ',msg or '').strip(); legs=[]
    for m in re.finditer(r'([A-Z][A-Z0-9\-/ .]{1,24}?)\s*/\s*(\d{1,3})\s*MI\s+(\d{1,3})\b', t):        # "WHEELING / 50 MI 44"
        legs.append((m.group(1).strip(), int(m.group(2)), int(m.group(3))))
    if not legs and 'MILES MIN' in t:                                                                    # "MILES MIN I-75 9 8 I-675 19 17"
        for m in re.finditer(r'([A-Z][A-Z0-9\-]{1,12})\s+(\d{1,3})\s+(\d{1,3})\b', t.split('MILES MIN',1)[1]):
            legs.append((m.group(1), int(m.group(2)), int(m.group(3))))
    out=[]
    for to,mi,mn in legs:
        if mi<=0 or mn<=0: continue
        mph=round(mi/(mn/60.0))
        out.append({'to':to.title() if to.isupper() and '-' not in to else to,'mi':mi,'min':mn,'mph':mph,'pace':'ok' if mph>=55 else ('slow' if mph>=40 else 'jam')})
    return out

def wx_summary(w):
    """Compact weather-station reading + hazard flag/reason."""
    surf=[s for s in (w.get('surf') or []) if s.get('st') and s['st'] not in ('Unknown','No description available')]
    statuses=sorted({s['st'] for s in surf}); temps=[sane_temp(s.get('t')) for s in surf]; temps=[t for t in temps if t is not None]
    atm=(w.get('atm') or [{}])[0]; air=sane_temp(atm.get('t')); vis=atm.get('vis'); precip=clean(atm.get('precip'))
    try: vis=float(vis)
    except: vis=None
    if vis is not None and vis<0: vis=None
    why=[]
    bad=[s for s in statuses if re.search(r'ice|icy|snow|frost|slush|freez', s, re.I)]
    if bad: why.append('/'.join(bad).upper()+' surface')
    if w.get('severe'): why.append('ODOT severe: '+clean(w.get('cond')) if w.get('cond') else 'ODOT severe weather flag')
    if re.search(r'snow|ice|sleet|freez|hail', precip, re.I): why.append(precip)
    if vis is not None and 0<vis<1: why.append(f'visibility {vis:g} mi')
    st_min=min(temps) if temps else None
    if st_min is not None and st_min<=34 and 'Wet' in statuses: why.append(f'wet pavement {st_min:.0f}°F — freeze risk')
    elif st_min is not None and st_min<=30: why.append(f'pavement {st_min:.0f}°F')
    return {'surface':'/'.join(statuses) or None,'surf_t':round(st_min) if st_min is not None else None,'air_t':round(air) if air is not None else None,
            'precip':precip if precip and precip.lower()!='none' else None,'vis':vis,'hazard':bool(why),'why':'; '.join(why) if why else None,'upd':atm.get('upd')}

def wx_loc(loc):
    """'D05 OH049FS GUE IR70 198.07- IR70 @ Fairview Twp line' -> 'I-70 @ Fairview Twp line'"""
    s=clean(loc); s=re.sub(r'^D\d+\s+\w+\s+\w{3}\s+','',s); s=re.sub(r'^IR(\d+)\s+[\d.]+\s*-\s*','',s)
    s=re.sub(r'\bIR(\d+)\b',r'I-\1',s); s=re.sub(r'\bSR(\d+)\b',r'SR-\1',s); s=re.sub(r'\bUS(\d+)\b',r'US-\1',s)
    return s.strip(' -')

# ---------------- per-pad ----------------
def match_alerts(pads, events, cat, now):
    hits={}
    for e in events:
        text=" ".join(clean(e.get(k)) for k in ('route','desc','loc')).lower()
        if cat=='construction':
            if not CLOSE_RE.search(text): continue
            if not is_active(e, now): continue
        if e.get('lat') is None: continue
        eroutes=set(norm_route(m.group(1),m.group(2)) for m in ROUTE_TYPE_RE.finditer(clean(e.get('route'))))
        for p in pads:
            dist=haversine_mi(p['lat'],p['lon'],e['lat'],e['lon'])
            if dist>PROX_MI: continue
            matched=False; why=""
            for nm in p['names']:
                if nm in text: matched=True; why=nm.title(); break
            if not matched and eroutes:
                common=p['appr'] & eroutes; nonI=[r for r in common if r[0]!='I']
                if nonI: matched=True
                elif common and dist<=INTERSTATE_MI: matched=True
            if matched:
                txt=f"{CATEGORY_LABEL.get(cat,cat)}: {clean(e.get('desc')) or clean(e.get('route'))}".strip()
                rn=clean(e.get('route'))
                if rn and rn.lower() not in txt.lower(): txt+=f" ({rn})"
                hits.setdefault(p['id'],[]).append(txt[:240])
    return hits

def pad_extras(pads, fx, now):
    padx={}
    cons=[c for c in fx['construction'] if is_active(c, now) and c.get('lat') is not None]
    for p in pads:
        x={}
        # --- active work zones on the route (any status, with dates) ---
        wz=[]
        if p['has_route']:
            for c in cons:
                text=" ".join(clean(c.get(k)) for k in ('route','desc','loc')).lower()
                croutes=set(norm_route(m.group(1),m.group(2)) for m in ROUTE_TYPE_RE.finditer(clean(c.get('route'))+" "+clean(c.get('loc'))))
                on_route=any(nm in text for nm in p['names']) or bool((croutes & p['routes']) - {r for r in croutes if r[0]=='I'})
                if not on_route: continue
                pts=[(c['lat'],c['lon'])]+[(q[1],q[0]) for pl in (c.get('pl') or []) for q in (pl or []) if q and len(q)==2]
                dmin=min(haversine_mi(p['lat'],p['lon'],a,b) for a,b in pts)
                if dmin>PROX_MI: continue
                wz.append({'t':clean(c.get('desc'))[:160] or clean(c.get('route')),'road':clean(c.get('route'))[:40],'status':clean(c.get('status')),
                           'start':fmt_date(c.get('start')),'end':fmt_date(c.get('end')),'mi':round(dmin,1)})
        if wz: x['wz']=sorted(wz,key=lambda w:w['mi'])[:3]
        # --- hazardous road surface nearby ---
        best=None
        for w in fx['weather']:
            if w.get('lat') is None: continue
            d=haversine_mi(p['lat'],p['lon'],w['lat'],w['lon'])
            if d>WX_MI: continue
            s=wx_summary(w)
            if not s['hazard']: continue
            if best is None or d<best[0]: best=(d,w,s)
        if best:
            d,w,s=best; x['wx']={'loc':wx_loc(w.get('loc')),'mi':round(d,1),**{k:s[k] for k in ('surface','surf_t','air_t','precip','vis','why')}}
        # --- nearest camera on a road the route actually uses ---
        if p['has_route']:
            bestc=None
            for c in fx['cameras']:
                if c.get('lat') is None or not c.get('u'): continue
                d=haversine_mi(p['lat'],p['lon'],c['lat'],c['lon'])
                if d>CAM_MI: continue
                cl=clean(c.get('loc')).lower()
                croutes=set(norm_route(m.group(1),m.group(2)) for m in ROUTE_TYPE_RE.finditer(clean(c.get('loc'))))
                if not (any(nm in cl for nm in p['names']) or (croutes & p['routes'])): continue
                if bestc is None or d<bestc[0]: bestc=(d,c)
            if bestc: d,c=bestc; x['cam']={'loc':clean(c.get('loc'))[:60],'url':c['u'],'mi':round(d,1)}
        if x: padx[p['id']]=x
    return padx

# ---------------- corridors ----------------
def build_corridors(fx, now):
    out=[]
    for cor in CORRIDORS:
        C={'id':cor['id'],'name':cor['name'],'label':cor['label'],'mm':cor['mm'],'traffic':{'delays':[],'slowdowns':[],'pace':[]},'incidents':[],'workzones':[],'weather':[],'cameras':[]}
        for e in fx['delays']:
            text=clean(e.get('route'))+' '+clean(e.get('loc'))+' '+clean(e.get('desc'))
            mm=None
            if e.get('mm0') is not None and e.get('mm1') is not None and cor['re'].search(text):
                lo,hi=sorted([float(e['mm0']),float(e['mm1'])]); a,b=cor['mm']
                if not (hi<a or lo>b): mm=(lo,hi)
            else: mm=in_corridor(cor,text,e.get('lat'),e.get('lon'))
            if mm: C['traffic']['delays'].append({'mm':[round(mm[0],1),round(mm[1],1)],'dir':dir_short(e.get('dir')),'delay':round(float(e.get('delay') or 0)),'cur':e.get('cur'),'normal':e.get('normal'),'desc':clean(e.get('desc'))[:140]})
        for e in fx['slowdowns']:
            text=clean(e.get('route'))+' '+clean(e.get('loc')); mm=in_corridor(cor,text,e.get('lat'),e.get('lon'))
            if mm: C['traffic']['slowdowns'].append({'mm':round(mm[0],1),'dir':dir_short(e.get('dir')),'cur':e.get('cur'),'normal':e.get('normal'),'loc':clean(e.get('loc'))[:60]})
        for s in fx['signs']:
            text=clean(s.get('loc')); mm=in_corridor(cor,text,s.get('lat'),s.get('lon'))
            if not mm: continue
            legs=[]
            for m in (s.get('msgs') or []): legs+=sign_legs(m)
            if legs:
                d='EB' if re.search(r'\bEB\b|east',text,re.I) else 'WB' if re.search(r'\bWB\b|west',text,re.I) else 'NB' if re.search(r'\bNB\b|north',text,re.I) else 'SB' if re.search(r'\bSB\b|south',text,re.I) else ''
                C['traffic']['pace'].append({'mm':round(mm[0],1),'dir':d,'loc':re.sub(r'^QWS:\s*','',text)[:50],'legs':legs[:4]})
        for e in fx['incidents']:
            rt=clean(e.get('route'))+' '+clean(e.get('loc'))
            if not cor['re'].search(rt): continue
            mm=in_corridor(cor,rt+' '+clean(e.get('desc')),e.get('lat'),e.get('lon'))
            if mm: C['incidents'].append({'mm':round(mm[0],1),'dir':dir_short(e.get('dir')),'cat':clean(e.get('cat')),'status':clean(e.get('status')),'desc':clean(e.get('desc')).split('\n')[0][:160]})
        for c in fx['construction']:
            if not is_active(c, now): continue
            rt=clean(c.get('route'))+' '+clean(c.get('loc')); text=rt+' '+clean(c.get('desc'))
            if not cor['re'].search(rt): continue
            pts=[(c.get('lat'),c.get('lon'))]+[(q[1],q[0]) for pl in (c.get('pl') or []) for q in (pl or []) if q and len(q)==2]
            mms=[mm_from_point(cor,a,b) for a,b in pts if a is not None and b is not None]
            lo,hi=parse_mm(text, cor.get('num'))
            if lo is None and mms: lo,hi=min(mms),max(mms)
            if lo is None: continue
            a,b=cor['mm']
            if hi<a-MM_SLOP or lo>b+MM_SLOP: continue
            C['workzones'].append({'mm':[round(max(lo,a),1),round(min(hi,b),1)],'dir':dir_short(c.get('dir')),'status':clean(c.get('status')),'desc':clean(c.get('desc'))[:170],'start':fmt_date(c.get('start')),'end':fmt_date(c.get('end')),'closure':(clean(c.get('status')).lower()=='closed' or bool(CLOSE_RE.search(clean(c.get('desc')))))})
        for w in fx['weather']:
            text=clean(w.get('loc')); mm=in_corridor(cor,text,w.get('lat'),w.get('lon'))
            if not mm: continue
            s=wx_summary(w)
            if s['surface'] is None and s['air_t'] is None: continue
            C['weather'].append({'mm':round(mm[0],1),'loc':wx_loc(text)[:50],**{k:s[k] for k in ('surface','surf_t','air_t','precip','vis','hazard','why')}})
        for c in fx['cameras']:
            text=clean(c.get('loc')); mm=in_corridor(cor,text,c.get('lat'),c.get('lon'))
            if mm and c.get('u'): C['cameras'].append({'mm':round(mm[0],1),'loc':text[:60],'url':c['u']})
        for k in ('incidents','workzones','weather','cameras'): C[k].sort(key=lambda r: r['mm'] if not isinstance(r['mm'],list) else r['mm'][0])
        C['traffic']['delays'].sort(key=lambda r:r['mm'][0]); C['traffic']['slowdowns'].sort(key=lambda r:r['mm']); C['traffic']['pace'].sort(key=lambda r:r['mm'])
        C['summary']={'delays':len(C['traffic']['delays']),'slowdowns':len(C['traffic']['slowdowns']),'incidents':len(C['incidents']),
                      'closures':sum(1 for z in C['workzones'] if z['closure']),'workzones':len(C['workzones']),
                      'wx_hazards':sum(1 for w in C['weather'] if w['hazard']),'cameras':len(C['cameras'])}
        out.append(C)
    return out

# ---------------- main ----------------
def main():
    fixtures=None
    if '--fixtures' in sys.argv: fixtures=sys.argv[sys.argv.index('--fixtures')+1]
    now=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    if fixtures:
        fx=json.load(open(fixtures)); print(f"using fixtures {fixtures} (pulled {fx.get('pulled')})")
    else:
        key=os.environ.get("OHGO_API_KEY")
        if not key: print("OHGO_API_KEY not set", file=sys.stderr); sys.exit(1)
        fx=fetch_all_live(key)
    print("feeds:", {k:len(v) for k,v in fx.items() if isinstance(v,list)})
    pads=load_pads(INDEX_PATH); print(f"pads with GPS: {len(pads)} (with routes: {sum(1 for p in pads if p['has_route'])})")
    allhits={}
    for cat,rows in (('construction',fx['construction']),('incidents',fx['incidents'])):
        h=match_alerts(pads,rows,cat,now)
        print(f"  {cat}: {len(rows)} events -> {sum(len(v) for v in h.values())} matches on {len(h)} pads")
        for k,v in h.items(): allhits.setdefault(k,[]).extend(v)
    # a frac is the same physical site as its pad card: any alert on a pad within FRAC_SITE_MI applies to the frac too
    fracs=[p for p in pads if p['src']=='Frac']
    for f in fracs:
        for p in pads:
            if p['src']=='Frac' or p['id'] not in allhits: continue
            if haversine_mi(f['lat'],f['lon'],p['lat'],p['lon'])<=FRAC_SITE_MI:
                allhits.setdefault(f['id'],[]).extend(allhits[p['id']])
    for k in allhits: allhits[k]=list(dict.fromkeys(allhits[k]))[:4]
    print(f"  frac inheritance: {sum(1 for f in fracs if f['id'] in allhits)} of {len(fracs)} fracs carry alerts")
    padx=pad_extras(pads,fx,now)
    print(f"  pad extras: work zones on {sum(1 for x in padx.values() if 'wz' in x)} pads, weather hazards on {sum(1 for x in padx.values() if 'wx' in x)}, cameras on {sum(1 for x in padx.values() if 'cam' in x)}")
    corridors=build_corridors(fx,now)
    for C in corridors: print(f"  {C['label']}: {C['summary']}")
    CAMHOST="https://itscameras.dot.state.oh.us"
    def shorten(u): return re.sub(r'^https://itscameras\.dot\.state\.oh\.us(?::443)?','',u or '')
    for x in padx.values():
        if 'cam' in x: x['cam']['url']=shorten(x['cam']['url'])
    for C in corridors:
        for c in C['cameras']: c['url']=shorten(c['url'])
    out={"updated":datetime.datetime.now(datetime.timezone.utc).isoformat(),"source":"OHGO (ODOT)","camhost":CAMHOST,"alerts":allhits,"padx":padx,"corridors":corridors}
    json.dump(out,open(OUT_PATH,'w'),separators=(',',':'))
    print(f"wrote {OUT_PATH}: {os.path.getsize(OUT_PATH)//1024} KB, {len(allhits)} pads flagged")

if __name__=="__main__":
    main()
