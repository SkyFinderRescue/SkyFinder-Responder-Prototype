#!/usr/bin/env python3
"""Index public PaddleSplash SUP result pages from Change of Pace."""
from __future__ import annotations
import argparse,json,re,urllib.request
from datetime import datetime,timezone
from html.parser import HTMLParser
from pathlib import Path

UA='SkyFinder-Paddler-Prototype/1.0 (+public race-result research)'
RACES={2022:6102,2023:6119,2024:6131,2025:6149}
BASE='https://results.changeofpace.com/results.aspx?CId=16356&RId={rid}&EId=1&dt=0'

class P(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.rows=[];self.r=None;self.c=None;self.b=[]
    def handle_starttag(self,t,a):
        t=t.lower()
        if t=='tr':self.r=[]
        elif t in ('td','th') and self.r is not None:self.c=t;self.b=[]
    def handle_data(self,d):
        if self.c is not None:self.b.append(d)
    def handle_endtag(self,t):
        t=t.lower()
        if t in ('td','th') and self.c is not None and self.r is not None:self.r.append(' '.join(' '.join(self.b).split()));self.c=None
        elif t=='tr' and self.r is not None:
            if self.r:self.rows.append(self.r)
            self.r=None

def fetch(u,timeout):
    req=urllib.request.Request(u,headers={'User-Agent':UA,'Accept':'text/html,*/*'})
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:return r.status,r.read().decode(r.headers.get_content_charset() or 'utf-8','replace')
    except Exception as e:return int(getattr(e,'code',0) or 0),''

def norm(s):return re.sub(r'[^a-z0-9]+',' ',(s or '').lower()).strip()
def plausible(s):
    s=' '.join((s or '').split())
    return bool(re.match(r"^[A-Za-z][A-Za-z'’.-]+(?:\s+[A-Za-z][A-Za-z'’.-]+){1,4}$",s)) and norm(s) not in {'overall results','first name last name','race results'}

def parse(text,year,url):
    p=P();p.feed(text);out=[]; headers=None
    for row in p.rows:
        low=[norm(x) for x in row]
        if any(x in {'name','runner name','participant','racer'} or 'name'==x for x in low):headers=low;continue
        name=None
        if headers:
            for label in ('name','runner name','participant','racer'):
                if label in headers:
                    i=headers.index(label)
                    if i<len(row):name=row[i]
                    break
        if not name:
            # result tables often place overall/place then bib then name
            for i,x in enumerate(row[:6]):
                if i>0 and plausible(x):name=x;break
        if not name or not plausible(name):continue
        joined=' | '.join(row)
        # PaddleSplash is SUP-only racing, but skip obvious clinic/non-race table fragments.
        if any(k in norm(joined) for k in ['sup yoga','clinic','parking']):continue
        out.append({'name':' '.join(name.split()),'year':year,'craft':'SUP','source_url':url})
    # de-dupe within year
    seen=set();d=[]
    for r in out:
        k=norm(r['name'])
        if k not in seen:seen.add(k);d.append(r)
    return d

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True);ap.add_argument('--timeout',type=int,default=20);a=ap.parse_args()
    audits=[];records=[]
    for year,rid in RACES.items():
        u=BASE.format(rid=rid);st,text=fetch(u,a.timeout);rows=parse(text,year,u) if st==200 else [];records+=rows;audits.append({'year':year,'race_id':rid,'url':u,'http_status':st,'bytes':len(text),'unique_names':len(rows)})
    people={}
    for r in records:
        k=norm(r['name']);p=people.setdefault(k,{'name':r['name'],'years':set()});p['years'].add(r['year'])
    plist=[{'name':v['name'],'years':sorted(v['years']),'crafts':['SUP']} for _,v in sorted(people.items())]
    out={'schema_version':1,'generated_at_utc':datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z'),'purpose':'Public PaddleSplash result identity index; not a live-location feed.','privacy':'Public displayed result names/year only.','summary':{'years_checked':len(audits),'years_http_200':sum(1 for x in audits if x['http_status']==200),'paddler_event_records':len(records),'unique_paddlers':len(plist)},'years':audits,'paddlers':plist,'records':records}
    Path(a.output).parent.mkdir(parents=True,exist_ok=True);Path(a.output).write_text(json.dumps(out,indent=2,ensure_ascii=False)+'\n',encoding='utf-8');print(json.dumps(out['summary'],indent=2))
if __name__=='__main__':main()
