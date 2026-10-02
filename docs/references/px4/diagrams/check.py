#!/usr/bin/env python3
"""Check generated SVG structure and readable size at an 800 px content width."""
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAMES = ('architecture', 'execution-contexts', 'uorb-delivery', 'topic-retention',
         'imu-acquisition', 'estimator-inputs', 'outer-control', 'fast-control',
         'nxrs-direction')
rows = []
for name in NAMES:
    path = HERE / (name + '.svg')
    data = path.read_text(encoding='utf-8')
    root = ET.fromstring(data)
    assert root.tag == '{http://www.w3.org/2000/svg}svg', path
    _, _, width, height = map(float, root.attrib['viewBox'].split())
    # Do not assume a CSS rule is used: examine actual SVG text elements.
    fonts = []
    for node in root.iter('{http://www.w3.org/2000/svg}text'):
        match = re.search(r'font-size\s*:\s*([\d.]+)', node.get('style', ''))
        if match:
            fonts.append(float(match.group(1)))
        elif node.get('font-size'):
            fonts.append(float(node.get('font-size').removesuffix('px')))
    assert fonts, (path, 'No explicit text sizes found')
    scale = min(1.0, 800.0 / width)
    min_font = min(fonts) * scale
    display_height = height * scale
    assert width > height, (path, width, height)
    assert display_height <= 440, (path, 'Too tall', display_height)
    assert min_font >= 14, (path, 'Text too small at 800 px', min_font)
    row = dict(name=name, width=width, height=height,
               height_at_800=round(display_height, 1), min_font_at_800=round(min_font, 1))
    rows.append(row)
    print(json.dumps(row))
(HERE / 'layout-metrics.json').write_text(json.dumps(rows, indent=2) + '\n')
