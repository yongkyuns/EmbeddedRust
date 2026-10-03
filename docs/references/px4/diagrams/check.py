#!/usr/bin/env python3
"""Check compact panels at 800 px and the standalone execution map at 1000 px."""
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAMES = ('architecture', 'execution-contexts', 'uorb-delivery', 'topic-retention',
         'imu-acquisition', 'estimator-inputs', 'outer-control', 'fast-control',
         'nxrs-direction', 'execution-map')
rows = []
for name in NAMES:
    path = HERE / (name + '.svg')
    data = path.read_text(encoding='utf-8')
    root = ET.fromstring(data)
    assert root.tag == '{http://www.w3.org/2000/svg}svg', path
    _, _, width, height = map(float, root.attrib['viewBox'].split())
    # Measure actual SVG text, not unused CSS declarations.
    fonts = []
    for node in root.iter('{http://www.w3.org/2000/svg}text'):
        match = re.search(r'font-size\s*:\s*([\d.]+)', node.get('style', ''))
        if match:
            fonts.append(float(match.group(1)))
        elif node.get('font-size'):
            fonts.append(float(node.get('font-size').removesuffix('px')))
    assert fonts, (path, 'No explicit text sizes found')
    scale800 = min(1.0, 800.0 / width)
    row = dict(name=name, width=width, height=height,
               height_at_800=round(height * scale800, 1),
               min_font_at_800=round(min(fonts) * scale800, 1))
    assert width > height, (path, 'Not landscape', width, height)
    if name == 'execution-map':
        # One full-page map, not a compact inline panel. Keep the 800 px
        # measurements visible; do not claim that this map passes that gate.
        reading_width, height_limit = 1000, 760
        assert width / height >= 1.35, (path, 'Insufficient landscape aspect')
        assert not list(root.iter('{http://www.w3.org/2000/svg}image')), path
    else:
        reading_width, height_limit = 800, 440
    scale = min(1.0, reading_width / width)
    assert height * scale <= height_limit, (path, 'Too tall', height * scale)
    assert min(fonts) * scale >= 14, (path, 'Text too small', reading_width)
    if name == 'execution-map':
        row.update(reading_width=reading_width,
                   height_at_reading_width=round(height * scale, 1),
                   min_font_at_reading_width=round(min(fonts) * scale, 1))
    rows.append(row)
    print(json.dumps(row))
(HERE / 'layout-metrics.json').write_text(json.dumps(rows, indent=2) + '\n')
