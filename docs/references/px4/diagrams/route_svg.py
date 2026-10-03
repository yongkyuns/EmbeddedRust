#!/usr/bin/env python3
"""Route D2 SVG connectors without changing node or container geometry.

Use after the pinned D2 v0.9.0 render. Routes are explicit, separately editable
waypoints in routes.json. D2 remains the source of graph topology and styling.
This is a post-render routing pass, not a second automatic block layout.
"""
from __future__ import annotations
import argparse, base64, hashlib, html, json, re
from pathlib import Path
import xml.etree.ElementTree as ET

SVG='http://www.w3.org/2000/svg'
ET.register_namespace('',SVG)
ET.register_namespace('xlink','http://www.w3.org/1999/xlink')
N={'s':SVG}

def edge_id(g: ET.Element)->str:
    return html.unescape(base64.b64decode(g.get('class','').split()[0]).decode())

def edges(root):
    return [g for g in root.iter(f'{{{SVG}}}g') if g.find('./s:path[@class="connection"]',N) is not None]

def node_snapshot(root):
    """Exact node positions, dimensions, styles, labels, and container groups."""
    return {g.get('class'):ET.tostring(g) for g in root.iter(f'{{{SVG}}}g')
            if g.find('./s:g[@class="shape"]',N) is not None}

def rounded_path(points,radius=6):
    if len(points)<2:raise ValueError('A route needs at least two points')
    pts=[(float(x),float(y)) for x,y in points]
    for a,b in zip(pts,pts[1:]):
        if a==b or (a[0]!=b[0] and a[1]!=b[1]):
            raise ValueError(f'Route must have nonzero orthogonal segments: {a}, {b}')
    fmt=lambda p:f'{p[0]:g},{p[1]:g}'
    d='M '+fmt(pts[0])
    for a,b,c in zip(pts,pts[1:],pts[2:]):
        if (a[0]==b[0]==c[0]) or (a[1]==b[1]==c[1]):
            d+=' L '+fmt(b);continue
        l1=abs(a[0]-b[0])+abs(a[1]-b[1]);l2=abs(c[0]-b[0])+abs(c[1]-b[1])
        r=min(radius,l1/2,l2/2)
        before=(b[0]+(a[0]-b[0])*r/l1,b[1]+(a[1]-b[1])*r/l1)
        after=(b[0]+(c[0]-b[0])*r/l2,b[1]+(c[1]-b[1])*r/l2)
        d+=' L '+fmt(before)+' Q '+fmt(b)+' '+fmt(after)
    return d+' L '+fmt(pts[-1])

def leaf_boxes(root):
    shapes=[]
    for g in root.iter(f'{{{SVG}}}g'):
        sh=g.find('./s:g[@class="shape"]/s:rect',N)
        if sh is None or g.get('style')=='opacity:0':continue
        shapes.append((edge_id(g),sh))
    for k,r in shapes:
        if any(k2.startswith(k+'.') for k2,_ in shapes):continue
        if float(r.get('width'))<=2:continue
        yield k,tuple(float(r.get(t)) for t in ('x','y','width','height'))

def crosses(a,b,box):
    x,y,w,h=box
    # Test centerlines against strict leaf-box interiors, not container backgrounds.
    x+=1;y+=1;w-=2;h-=2
    if a[0]==b[0]:return x<a[0]<x+w and max(min(a[1],b[1]),y)<min(max(a[1],b[1]),y+h)
    return y<a[1]<y+h and max(min(a[0],b[0]),x)<min(max(a[0],b[0]),x+w)

def route_file(source:Path,target:Path,configs:list[dict]):
    root=ET.parse(source).getroot();before=node_snapshot(root)
    es=edges(root);index={edge_id(g):g for g in es}
    if len(index)!=len(es):raise ValueError('Duplicate edge identifiers')
    if set(index)!=set(c['edge'] for c in configs):
        raise ValueError('Routing specification does not match diagram topology')
    collisions=[];boxes=list(leaf_boxes(root))
    for c in configs:
        g=index[c['edge']];p=g.find('./s:path[@class="connection"]',N)
        pts=c['points'];p.set('d',rounded_path(pts));p.attrib.pop('mask',None)
        p.set('stroke-linejoin','round');p.set('stroke-linecap','round')
        for a,b in zip(pts,pts[1:]):
            for key,box in boxes:
                if crosses(a,b,box):collisions.append({'edge':c['edge'],'node':key,'segment':[a,b]})
        label=c.get('label');t=g.find('./s:text',N)
        if label and t is not None:
            old=' '.join(t.itertext()).strip();lines=label.get('lines') or [old]
            if re.sub(r'\s+', '', old) != re.sub(r'\s+', '', ''.join(lines)):
                raise ValueError('Connector label content changed')
            size=label.get('font_size') or float(re.search(r'font-size:([\d.]+)',t.get('style','')).group(1))
            x=label['x'];y=label['y'];style=re.sub(r'font-size:[\d.]+px',f'font-size:{size:g}px',t.get('style',''))
            t.set('x',str(x));t.set('y',str(y));t.set('style',style+';paint-order:stroke;stroke:white;stroke-width:5;stroke-linejoin:round;')
            for child in list(t):t.remove(child)
            t.text=None
            for i,line in enumerate(lines):
                span=ET.SubElement(t,f'{{{SVG}}}tspan',{'x':str(x),'dy':'0' if i==0 else f'{size*1.18:g}'})
                span.text=line
    if node_snapshot(root)!=before:raise AssertionError('Routing changed a node group')
    target.parent.mkdir(parents=True,exist_ok=True)
    ET.ElementTree(root).write(target,encoding='utf-8',xml_declaration=True)
    return {'name':source.stem,'node_groups_unchanged':len(before),'edges_routed':len(configs),
            'block_interior_intersections':collisions}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input-dir',type=Path,required=True)
    ap.add_argument('--output-dir',type=Path,required=True)
    ap.add_argument('--routes',type=Path,default=Path(__file__).with_name('routes.json'))
    a=ap.parse_args();spec=json.loads(a.routes.read_text());reports=[]
    for name,cfg in spec['diagrams'].items():
        raw=(a.input_dir/(name+'.svg')).read_bytes()
        blob=hashlib.sha1(f'blob {len(raw)}\0'.encode()+raw).hexdigest()
        if blob != spec['raw_svg_blobs'][name]:
            raise ValueError('Baseline SVG changed; review routes before regenerating '+name)
        reports.append(route_file(a.input_dir/(name+'.svg'),a.output_dir/(name+'.svg'),cfg))
    report={'baseline_commit':spec['baseline_commit'],'routing':reports}
    (a.output_dir/'routing-checks.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    if any(r['block_interior_intersections'] for r in reports):raise SystemExit('Routes intersect a node interior')
if __name__=='__main__':main()
