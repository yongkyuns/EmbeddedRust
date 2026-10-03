# Diagram layout and reproduction

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
d2 --layout=elk --theme=0 --pad=16 \
  docs/references/px4/diagrams/sensor-to-ekf-execution-map.d2 \
  docs/references/px4/diagrams/sensor-to-ekf-execution-map.svg
```

Set `D2=/absolute/path/to/d2` when needed. Do not hand-edit generated SVGs. The verified Linux-amd64 D2 v0.9.0 archive SHA-256 is `5669ddc46b99e942cc96078f4a4e36d5e62103348f4c05179ede27802fdd87a9`; other platforms require their own official checksum.

[Analysis](../README.md) · [Source evidence](../sources.md) · [nxrs implications](../nxrs-design-notes.md)
