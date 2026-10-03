#!/usr/bin/env python3
"""Regression checks for the three deliberately horizontal-wired PX4 maps.

Checks SVG stroke centerlines against opaque rectangular blocks (4 px inset),
wire/wire overlaps, landscape ratio and embedded images. Sequence lifelines and
sequence-group background rectangles are not signal wires or obstacles.
This complements, and does not replace, browser label/visual inspection.
"""
import base64
import html
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAMES = ('sensor-to-ekf-execution-map', 'execution-loops-data-flow', 'execution-map')
EXPECTED_WIRES = dict(zip(NAMES, (12, 4, 7)))
NS = '{http://www.w3.org/2000/svg}'


def object_id(group):
    try:
        return html.unescape(base64.b64decode(group.get('class', '').split()[0], validate=True).decode())
    except (ValueError, IndexError, UnicodeError):
        return ''


def segments(path):
    # Do not silently skip new curves/transforms; a changed routing style needs review.
    d = path.get('d', '')
    assert not re.search(r'[A-KN-Za-kn-z]', d), ('Expected only absolute M/L paths', d)
    tokens = re.findall(r'[ML]|-?(?:\d+(?:\.\d*)?|\.\d+)', d)
    points = []
    i = 0
    while i < len(tokens):
        if tokens[i] in ('M', 'L'):
            i += 1
        points.append((float(tokens[i]), float(tokens[i + 1])))
        i += 2
    return list(zip(points, points[1:]))


def hits_box(seg, box, inset=4):
    (x0, y0), (x1, y1) = seg
    x, y, w, h = box
    assert abs(y0 - y1) < 0.01, ('Signal wire must be horizontal', seg)
    return (y + inset < y0 < y + h - inset
            and max(min(x0, x1), x + inset) < min(max(x0, x1), x + w - inset))


def overlap(a, b):
    (ax0, ay), (ax1, _) = a
    (bx0, by), (bx1, _) = b
    return (abs(ay - by) < 0.01
            and max(min(ax0, ax1), min(bx0, bx1)) + 0.01 < min(max(ax0, ax1), max(bx0, bx1)))


def check(path):
    root = ET.parse(path).getroot()
    assert root.tag == NS + 'svg', path
    _, _, w, h = map(float, root.get('viewBox').split())
    assert w / h >= 1.45, (path, 'Not sufficiently landscape', w, h)
    assert not list(root.iter(NS + 'image')), (path, 'Embedded image')
    boxes, wires = [], []
    lifelines = 0
    for group in root.iter(NS + 'g'):
        name = object_id(group)
        if not name:
            continue
        assert not group.get('transform'), (path, name, 'Unexpected group transform')
        rect = group.find('./' + NS + 'g/' + NS + 'rect')
        if rect is not None and rect.get('fill') not in ('transparent', 'none'):
            if name not in ('trace.imu', 'trace.gnss'):
                boxes.append((name, tuple(float(rect.get(k, '0')) for k in ('x', 'y', 'width', 'height'))))
        for stroke in group.findall('./' + NS + 'path'):
            if stroke.get('class') != 'connection':
                continue
            if ' -- )' in name:
                lifelines += 1
                continue
            for seg in segments(stroke):
                assert abs(seg[0][1] - seg[1][1]) < 0.01, (path, name, 'Non-horizontal signal')
                wires.append((name, seg))
    assert len(wires) == EXPECTED_WIRES[path.stem], (path, 'Missing/extra wires', len(wires))
    collisions = [(wire, block) for wire, line in wires for block, box in boxes if hits_box(line, box)]
    overlaps = [(na, nb) for i, (na, a) in enumerate(wires) for nb, b in wires[i + 1:] if overlap(a, b)]
    assert not collisions, (path, 'Wire passes through a block', collisions)
    assert not overlaps, (path, 'Wires overlap', overlaps)
    return dict(name=path.stem, signal_wires=len(wires), tested_blocks=len(boxes),
                excluded_sequence_lifelines=lifelines, wire_block_intersections=0,
                signal_wire_overlaps=0, width=w, height=h)


if __name__ == '__main__':
    # Exercise positive/negative checks, so "no collisions" is not an empty test.
    assert hits_box(((0, 10), (100, 10)), (40, 0, 20, 20))
    assert not hits_box(((0, 30), (100, 30)), (40, 0, 20, 20))
    assert overlap(((0, 10), (100, 10)), ((40, 10), (60, 10)))
    assert not overlap(((0, 10), (100, 10)), ((40, 30), (60, 30)))
    rows = [check(HERE / (name + '.svg')) for name in NAMES]
    (HERE / 'wiring-metrics.json').write_text(json.dumps(rows, indent=2) + '\n')
    print(json.dumps(rows, indent=2))
