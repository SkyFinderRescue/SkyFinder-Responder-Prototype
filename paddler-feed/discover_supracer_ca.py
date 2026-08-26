#!/usr/bin/env python3
"""Index public California SUP race identities from SUP Racer's historical results archive."""
from __future__ import annotations
import argparse, html, json, re, time, urllib.parse, urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

UA='SkyFinder-Paddler-Prototype/1.0 (+public SUP results archive research)'
INDEX='https://supracer.com/results/'

def fetch(url,timeout):
    req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'text/html,*/*'})
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:return r.status,r.read().decode(r.headers.get_content_charset() or 'utf-8','replace'),r.geturl()
    except Exception as e:return int(getattr(e,'code',0) or 0),'',url

def norm(s):return re.sub(r'[^a-z0-9]+',' ',html.unescape(s or '').lower()).strip()
def clean(s):return ' '.join(html.unescape(re.sub(r'<[^>]+>',' ',s or '')).split())

class RowParser(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.rows=[];self.row=None;self.cell=None;self.buf=[];self.links=[]
    def handle_starttag(self,tag,attrs):
        t=tag.lower()
        if t=='tr':self.row=[]
        elif t in ('td','th') and self.row is not None:self.cell=t;self.buf=[];self.links=[]
        elif t=='a' and self.cell is not None:
            h=dict(attrs).get('href')
            if h:self.links.append(h)
    def handle_data(self,d):
        if self.cell is not None:self.buf.append(d)
    def handle_endtag(self,tag):
        t=tag.lower()
        if t in ('td','th') and self.cell is not None and self.row is not None:
            self.row.append({'text':' '.join(' '.join(self.buf).split()),'links':self.links[:]});self.cell=None
        elif t=='tr' and self.row is not None:
            if self.row:self.rows.append(self.row)
            self.row=None

def ca_event_links(text):
    p=RowParser();p.feed(text);out=[]
    for row in p.rows:
        joined=' | '.join(c['text'] for c in row)
        if 'california' not in joined.lower():continue
        urls=[]
        for c in row:
            for h in c['links']:
                u=urllib.parse.urljoin(INDEX,h)
                if 'supracer.com' in u and '/results/' not in u.rstrip('/').lower():urls.append(u)
        # Keep all event article links; rows often also include unrelated taxonomy links.
        for u in urls:
            if u not in [x['url'] for x in out]:out.append({'url':u,'index_row':joined[:500]})
    # Fallback: context around any href whose nearby text says California.
    if not out:
        for m in re.finditer(r'href=["\']([^"\']+)["\']',text,re.I):
            ctx=clean(text[max(0,m.start()-500):m.end()+500])
            if 'california' in ctx.lower():
                u=urllib.parse.urljoin(INDEX,m.group(1));
                if 'supracer.com' in u:out.append({'url':u,'index_row':ctx[:500]})
    return out

def extract_table_names(text):
    p=RowParser();p.feed(text);names=[];seen=set()
    headers=[]
    for row in p.rows:
        vals=[c['text'].strip() for c in row]
        low=[norm(v) for v in vals]
        if 'name' in low:
            headers=low;continue
        if not vals:continue
        name=None
        if headers and 'name' in headers:
            idx=headers.index('name')
            if idx < len(vals):name=vals[idx]
        if not name:
            # Common SUP Racer table: rank | name | time or sex/rank/time/name/class.
            for i,v in enumerate(vals):
                if i==0:continue
                if re.match(r"^[A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){1,3}$",v):name=v;break
        if not name:continue
        n=norm(name)
        if n in {'name','men elite','women elite'} or any(x in n for x in ['results','distance race','elite race','open race']):continue
        if n not in seen:seen.add(n);names.append(name)
    return names

def event_year(text,url):
    m=re.search(r'\b(200[8-9]|201\d|202\d)\b',url+' '+clean(text[:5000]))
    return int(m.group(1)) if m else None

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True);ap.add_argument('--timeout',type=int,default=20);ap.add_argument('--sleep',type=float,default=.03);ap.add_argument('--max-events',type=int,default=300);args=ap.parse_args()
    st,index,_=fetch(INDEX,args.timeout);links=ca_event_links(index) if st==200 else []
    # Seed historically important California full-result pages that search indexes expose even if archive row links are inconsistent.
    seeds=['https://supracer.com/battle-of-the-paddle-live-blog/','https://supracer.com/2013-dana-point-ocean-challenge-results/','https://supracer.com/results-dana-point-ocean-challenge-docc/','https://supracer.com/2009-battle-of-the-paddle-results-video/']
    for u in seeds:
        if not any(x['url']==u for x in links):links.append({'url':u,'index_row':'historical California SUP result seed'})
    audit=[];appear=[]
    for item in links[:args.max_events]:
        url=item['url'];s,t,final=fetch(url,args.timeout);names=extract_table_names(t) if s==200 else [];yr=event_year(t,url);title=''
        mt=re.search(r'<title[^>]*>(.*?)</title>',t,re.I|re.S)
        if mt:title=clean(mt.group(1))[:200]
        for name in names:appear.append({'name':name,'year':yr,'event':title or item['index_row'][:150],'source_url':url,'craft':'SUP'})
        audit.append({'url':url,'http_status':s,'year':yr,'title':title,'names':len(names),'index_context':item['index_row']})
        if args.sleep:time.sleep(args.sleep)
    seen=set();ded=[]
    for r in appear:
        k=(norm(r['name']),r.get('year'),r['source_url'])
        if k not in seen:seen.add(k);ded.append(r)
    people={}
    for r in ded:
        k=norm(r['name']);p=people.setdefault(k,{'name':r['name'],'years':set(),'sources':set()});
        if r.get('year'):p['years'].add(r['year'])
        p['sources'].add(r['source_url'])
    plist=[{'name':v['name'],'years':sorted(v['years']),'source_count':len(v['sources']),'crafts':['SUP']} for _,v in sorted(people.items())]
    out={'schema_version':1,'generated_at_utc':datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z'),'purpose':'Public SUP Racer California historical result identity index; not a live-location feed.','privacy':'Public race-result names/year/source only.','summary':{'index_http_status':st,'california_event_links':len(links),'event_pages_checked':len(audit),'event_pages_http_200':sum(1 for a in audit if a['http_status']==200),'event_pages_with_names':sum(1 for a in audit if a['names']>0),'paddler_event_records':len(ded),'unique_paddlers':len(plist)},'events':audit,'paddlers':plist,'records':ded}
    Path(args.output).parent.mkdir(parents=True,exist_ok=True);json.dump(out,open(args.output,'w',encoding='utf-8'),indent=2,ensure_ascii=False);open(args.output,'a').write('\n');print(json.dumps(out['summary'],indent=2))
if __name__=='__main__':main()
