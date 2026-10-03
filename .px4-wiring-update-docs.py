from pathlib import Path
root = Path('docs/references/px4')
p = root / 'README.md'
s = p.read_text()
start, end = s.index('## Start here:'), s.index('## The essential distinction')
assert start < end
intro = '''## Start here: execution, data and wakeups

The three primary D2 views have been fully relaid out to remove cross-block wiring. They keep the same PX4 sensor-to-EKF scope, but no longer try to match the earlier raster geometry. Open the standalone SVGs for reading; the inline images are previews.

### 1. Sensor-to-EKF overview

![PX4 sensor-to-EKF overview with separate IMU and GNSS lanes](diagrams/sensor-to-ekf-execution-map.svg)

[Editable D2](diagrams/sensor-to-ekf-execution-map.d2) · [Full-size SVG](diagrams/sensor-to-ekf-execution-map.svg)

The upper row shows hardware/OS entry. The IMU and GNSS rows then show processing and topic handoffs left to right. **Repeated A/B/C/D labels are references to the same four execution contexts**, not new threads. In particular, VehicleIMU and EKF2 both run on B (`wq:INS0`), and the voter and GNSS processing both run on C (`wq:nav_and_controllers`). [Worker][worker] · [EKF2][ekf] · [GPS driver][gps]

Teal links abstract publication into retained uORB storage and the consumer's later read; they are not direct calls into the consumer. Orange dashed links separately identify callback scheduling. GNSS's final `vehicle_gnss` link is **data only, with no GNSS-triggered EKF2 wake** in this path. No common data bus or central dispatcher is implied. [Publication][node] · [Callback][callback] · [EKF2][ekf]

### 2. Execution-context ownership and the control-side path

![PX4 worker cards with nested modules and a separate control-flow row](diagrams/execution-loops-data-flow.svg)

[Editable D2](diagrams/execution-loops-data-flow.d2) · [Full-size SVG](diagrams/execution-loops-data-flow.svg)

Each card is one OS execution context. Nested boxes are the work items it calls, not additional loops. Containment replaces the earlier scheduler-to-every-module wiring. The control worker E is included, and its data path is shown in its own horizontal row. Card order does not prescribe dispatch order. These selected contexts are not the total firmware thread count. [Worker][worker] · [Gyro processing][angular] · [Rate control][rate] · [Allocation][allocation]

### 3. Four-loop sequence view

![Four PX4 execution loops and OS services with horizontal causal handoffs](diagrams/execution-map.svg)

[Editable D2](diagrams/execution-map.d2) · [Full-size SVG](diagrams/execution-map.svg)

The sequence view keeps one lifeline for each A-D context plus IRQ/OS services, which are **not a fifth processing loop**. Messages run horizontally below the header boxes. Teal messages combine a topic handoff with its scheduling annotation; the overview above separates those wires. IMU and GNSS are separate causal examples, not a global event order or measured timing trace. [Driver ISR][icm] · [Worker][worker] · [Callback][callback] · [EKF2][ekf]

All three use the same pinned single-estimator, NuttX flat-build example. PX4 `wq:*` workers are not NuttX HPWORK/LPWORK, and the logical OS/application split is not a protected address-space boundary. These maps use a **1500 px standalone reading width** (minimum rendered text approximately 14.6–17.2 px), not an 800 px thumbnail readability claim. [Layout measurements and reproduction](diagrams/README.md)

'''
p.write_text(s[:start] + intro + s[end:])
(root / 'diagrams/README.md').write_text('''# Diagram layout and reproduction

## Three primary views: full wiring relayout

The files retain their names but prioritize legibility over reproducing the earlier raster geometry. All are editable, self-contained D2 with generated SVG output.

| View | Source / SVG | Native size | Height at 1500 px | Minimum text at 1500 px |
| --- | --- | --- | --- | --- |
| Sensor-to-EKF overview | [D2](sensor-to-ekf-execution-map.d2) / [SVG](sensor-to-ekf-execution-map.svg) | 2388 × 1274 | 800.3 px | 15.1 px |
| Execution ownership + control | [D2](execution-loops-data-flow.d2) / [SVG](execution-loops-data-flow.svg) | 2468 × 1322 | 803.5 px | 14.6 px |
| Four-loop sequence | [D2](execution-map.d2) / [SVG](execution-map.svg) | 2094 × 1391 | 996.4 px | 17.2 px |

These are full-page diagrams. At 800 px the minimum labels are only about 7.8–9.2 px; open the standalone SVG rather than treating an inline preview as the reading view. `layout-metrics.json` records both the 800 px measurements and each figure's actual reading-width gate.

## Wiring rules

Use regular left-to-right ELK graphs **inside** the overview's independent hardware, IMU and GNSS rows. There are no cross-grid edges. Adjacent-stage payload and scheduling links use parallel, non-overlapping paths. Repeated B/C labels refer to the same worker contexts; they do not add threads or queues. Do not connect distinct topics into a fictitious shared bus merely to tidy the drawing.

Use containment for execution ownership: one card per OS context, nested module boxes, and no scheduler-to-every-module wires. Keep the control data path in a separate row. Use D2's native `sequence_diagram` for the four-loop view: horizontal messages and distinct IMU/GNSS groups below the actor headers. Sequence lifeline/message intersections are intentional; they are not intersecting signal wires.

Teal means a uORB data handoff, orange dashed means scheduling, and grey means OS/device I/O. In the sequence view the teal message labels also state when a callback schedules the consumer. An arrow never guarantees one raw sample, context switch, or filter update. GNSS's final link does not wake EKF2 in the shown configuration. The source snapshot and semantic qualifications remain in the main analysis.

D2's documented grid behavior explains the previous crossings: with ELK/Dagre, edges between grid cells are straight segments without path-finding. [Grid connections](https://d2lang.com/tour/grid-diagrams/#connections-between-grid-cells) · [Sequence diagrams](https://d2lang.com/tour/sequence-diagrams/)

## Checks and limitations

`render.sh` compiles all **14** D2 sources with D2 v0.9.0, ELK, theme 0 and 16 px padding. `check.py` checks XML, landscape and actual text sizes. The original nine compact panels retain their 800 px / minimum-14-px / maximum-440-px gates. The two supplemental IMU/GNSS traces retain their 1200 px gates. The three primary maps use 1500 px / minimum-14-px / maximum-1100-px gates and aspect ratio at least 1.45. No existing compact-panel gate is weakened.

`check-wiring.py` checks all **23 signal wires** in the three primary maps: 12 in the overview, 4 in the control row and 7 in the sequence view. It rejects non-horizontal signal routes, stroke-centerline intersections with opaque rectangular block interiors (4 px inset), and overlapping signal wires. It excludes the sequence lifelines and sequence-group backgrounds. Counts are explicit so deleting wires does not make the test pass. Positive/negative synthetic checks exercise the collision predicates. Results are written to `wiring-metrics.json`.

The geometry checker is deliberately narrow: it does not prove semantic correctness or replace browser inspection of typography, masks, arrowheads and labels. The three primary SVGs were also rendered and visually inspected in Chromium; browser geometry checks found no text extending outside its own box and no signal wire crossing another label. A wire masked behind its own label is intentional.

## Reproduce

Requirements: D2 v0.9.0 and Python 3.9+.

```sh
bash docs/references/px4/diagrams/render.sh
# Or just one figure:
d2 --layout=elk --theme=0 --pad=16 \\
  docs/references/px4/diagrams/sensor-to-ekf-execution-map.d2 \\
  docs/references/px4/diagrams/sensor-to-ekf-execution-map.svg
```

Set `D2=/absolute/path/to/d2` when needed. Do not hand-edit generated SVGs. The verified Linux-amd64 D2 v0.9.0 archive SHA-256 is `5669ddc46b99e942cc96078f4a4e36d5e62103348f4c05179ede27802fdd87a9`; other platforms require their own official checksum.

[Analysis](../README.md) · [Source evidence](../sources.md) · [nxrs implications](../nxrs-design-notes.md)
''')
render = root / 'diagrams/render.sh'
s = render.read_text()
assert s.count('python3 check.py') == 1
render.write_text(s.replace('python3 check.py', 'python3 check.py\npython3 check-wiring.py'))
