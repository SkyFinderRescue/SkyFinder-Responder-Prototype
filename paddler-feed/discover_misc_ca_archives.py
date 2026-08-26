#!/usr/bin/env python3
"""Index independent public California SUP/prone/surfski/outrigger result archives."""
from __future__ import annotations
import argparse, io, json, re, time, urllib.parse, urllib.request
from collections import defaultdict, deque
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

UA='SkyFinder-Paddler-Prototype/1.0 (+public result archive research)'
CRAFT_TERMS=('SUP','Stand Up Paddle','Stand-Up Paddle','Prone','Paddleboard','SurfSki','Surfski','Outrigger','OC1','OC-1','OC2','OC-2','Kayak')

def fetch(url,timeout):
    req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'text/html,application/pdf,*/*'})
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:
            return r.status,r.headers.get_content_type(),r.read(),r.geturl()
    except Exception as e:
        return int(getattr(e,'code',0) or 0),None,b'',url

def strip_html(s):
    s=re.sub(r'<script\b.*?</script>|<style\b.*?</style>',' ',s or '',flags=re.I|re.S)
    s=re.sub(r'<br\s*/?>|</tr>|</p>|</li>|</div>|</h\d>','\n',s,flags=re.I)
    s=unescape(re.sub(r'<[^>]+>',' ',s))
    return '\n'.join(' '.join(x.split()) for x in s.splitlines() if ' '.join(x.split()))

def pdf_text(data):
    try:
        from pypdf import PdfReader
        return '\n'.join((p.extract_text() or '') for p in PdfReader(io.BytesIO(data)).pages)
    except Exception:return ''

def classify(s):
    t=(s or '').lower()
    if 'stand up paddle' in t or 'stand-up paddle' in t or re.search(r'\bsup\b',t): return 'SUP'
    if 'prone' in t or 'paddleboard' in t: return 'PRONE/PADDLEBOARD'
    if 'surfski' in t or 'surf ski' in t: return 'SURFSKI'
    if 'outrigger' in t or re.search(r'\boc[- ]?[12]\b',t): return 'OUTRIGGER'
    if 'kayak' in t:return 'KAYAK'
    return None

def norm(s):return re.sub(r'[^a-z0-9]+',' ',(s or '').lower()).strip()

def name_candidates(text):
    out=[];seen=set(); lines=(text or '').splitlines()
    bad=('results','paddleboard','stand up paddle','surfski','outrigger','kayak','female','male','division','overall','course','place','trophy','race','club','category','watercraft','finish','contact','sponsor')
    for i,line in enumerate(lines):
        s=' '.join(line.split())
        if not s or len(s)>220:continue
        window=' '.join(lines[max(0,i-1):min(len(lines),i+2)])
        craft=classify(window)
        if not craft:continue
        # Table-like PDF/HTML text: strip place/bib/time then capture plausible human name.
        x=re.sub(r'^\s*(?:\d+(?:st|nd|rd|th)?|DNF|DQ)\s*[|,:-]*\s*','',s,flags=re.I)
        # Named-column format.
        m=re.search(r'\bName\s+([A-Z][A-Za-z\'’.-]+(?:\s+(?:[A-Z][A-Za-z\'’.-]+|[a-z]{2,4})){1,4})(?=\s+(?:Club|Watercraft|Division|Race|Rally|SUP|Prone|Kayak|Surfski|Outrigger|Finish|\d))',x)
        if not m:
            m=re.match(r'^(?:\d+\s+)?([A-Z][A-Za-z\'’.-]+(?:\s+[A-Z][A-Za-z\'’.-]+){1,3})(?=\s)',x)
        if not m:continue
        name=' '.join(m.group(1).split())
        n=norm(name)
        if any(b in n for b in bad) or len(name)<5:continue
        key=(n,craft)
        if key not in seen:
            seen.add(key);out.append({'name':name,'craft':craft})
    return out

def discover_links(base,html_text):
    out=set()
    for href in re.findall(r'href=["\']([^"\']+)',html_text or '',flags=re.I):
        u=urllib.parse.urljoin(base,unescape(href))
        low=u.lower()
        if any(k in low for k in ('result','biltmore','paddle','sup','race')) and not low.startswith(('mailto:','javascript:')):
            out.add(u.split('#')[0])
    return out

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--sources',required=True);ap.add_argument('--output',required=True);ap.add_argument('--timeout',type=int,default=20);ap.add_argument('--sleep',type=float,default=.03);ap.add_argument('--max-linked',type=int,default=100);args=ap.parse_args()
    cfg=json.load(open(args.sources,encoding='utf-8'))
    docs=[]; records=[]
    for src in cfg['sources']:
        q=deque([(src['url'],0)]); visited=set()
        while q and len(visited)<args.max_linked:
            url,depth=q.popleft()
            if url in visited:continue
            visited.add(url)
            st,ctype,data,final=fetch(url,args.timeout); text='';mode=None
            if st==200 and data:
                if ctype=='application/pdf' or final.lower().split('?')[0].endswith('.pdf'):
                    text=pdf_text(data);mode='pdf-text' if text.strip() else 'pdf-unreadable'
                else:
                    raw=data.decode('utf-8','replace');text=strip_html(raw);mode='html-text'
                    if src['kind']=='index' and depth==0:
                        for u in discover_links(final,raw):
                            if u not in visited:q.append((u,depth+1))
            found=name_candidates(text)
            for r in found:
                records.append({**r,'archive':src['name'],'region':src['region'],'source_url':url})
            docs.append({'archive':src['name'],'url':url,'http_status':st,'content_type':ctype,'parse_mode':mode,'candidate_records':len(found)})
            if args.sleep:time.sleep(args.sleep)
    # Cross-source conservative name/craft index.
    seen=set();ded=[]
    for r in records:
        k=(norm(r['name']),r['craft'],r['source_url'])
        if k not in seen:seen.add(k);ded.append(r)
    people={}
    for r in ded:
        k=norm(r['name']);p=people.setdefault(k,{'name':r['name'],'crafts':set(),'sources':set(),'archives':set()});p['crafts'].add(r['craft']);p['sources'].add(r['source_url']);p['archives'].add(r['archive'])
    plist=[{'name':v['name'],'crafts':sorted(v['crafts']),'source_count':len(v['sources']),'archives':sorted(v['archives'])} for _,v in sorted(people.items())]
    counts=defaultdict(int)
    for p in plist:
        for c in p['crafts']:counts[c]+=1
    out={'schema_version':1,'generated_at_utc':datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z'),'purpose':'Independent public California paddle result archive coverage index; not a live-location feed.','privacy':'Public race-result identity/craft/source metadata only; no private contact information or exact live GPS.','summary':{'archives_configured':len(cfg['sources']),'documents_checked':len(docs),'documents_http_200':sum(1 for d in docs if d['http_status']==200),'paddler_result_records':len(ded),'unique_paddlers':len(plist),'craft_counts':dict(sorted(counts.items()))},'documents':docs,'paddlers':plist,'records':ded}
    Path(args.output).parent.mkdir(parents=True,exist_ok=True);json.dump(out,open(args.output,'w',encoding='utf-8'),indent=2,ensure_ascii=False);open(args.output,'a').write('\n');print(json.dumps(out['summary'],indent=2))
if __name__=='__main__':main()
