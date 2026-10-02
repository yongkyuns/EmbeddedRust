# Diagram layout and reproduction

These are actual D2 sources with checked-in SVG output. They use a local **Material-style palette**, adapted from the Zephyr reference, not a named built-in D2 theme. There are no imports from other reference directories.

## Layout contract

Use left-to-right landscape panels with 20 px source labels and explicit, compact node sizes. Split the outer and inner control paths instead of stretching one unreadable mega-diagram. Put implementation qualifications in the surrounding prose rather than tiny arrow labels. Colors distinguish application, contract, implementation, adaptation and hardware roles; captions identify whether each panel represents data, scheduling or dependencies.

Dashed edges mean scheduling/notification in the applicable figures. Solid edges mean data or dependency as the caption specifies. No diagram claims one context switch, one sample or one handler per arrow. The estimator panel's fusion/prediction boxes are conceptual phases, not separate tasks. The nxrs panel is proposed nxrs behavior, not PX4.

## Measured presentation

The checker uses actual SVG text sizes and `viewBox`, scaling down to an 800 px reading width without assuming enlargement. These are layout measurements, not system performance measurements.

| Figure | Native SVG dimensions | Height at 800 px | Minimum label size at 800 px |
| --- | --- | --- | --- |
| Architecture | 1036 × 226 | 174.5 px | 15.4 px |
| Execution contexts | 812 × 410 | 403.9 px | 19.7 px |
| uORB delivery | 1020 × 226 | 177.3 px | 15.7 px |
| Topic retention | 818 × 238 | 232.8 px | 19.6 px |
| IMU acquisition | 1046 × 238 | 182.0 px | 15.3 px |
| Estimator inputs | 1062 × 238 | 179.3 px | 15.1 px |
| Outer control | 1058 × 126 | 95.3 px | 15.1 px |
| Fast control | 1088 × 238 | 175.0 px | 14.7 px |
| Proposed nxrs direction | 1122 × 338 | 241.0 px | 14.3 px |

The execution-context panel is intentionally taller to distinguish three OS contexts; the other panels occupy roughly 95–241 px at reading width. All nine were visually inspected in Chromium at 800 px. Narrow mobile layouts may need opening/zooming the SVG; the 800 px checks do not establish readability at every viewport.

## Reproduce

Requirements: **D2 v0.9.0** and Python 3.9 or newer. From the repository root:

```sh
bash docs/references/px4/diagrams/render.sh
```

Or set `D2=/absolute/path/to/d2`. The script checks the renderer version, uses ELK, theme 0 and 16 px padding, then validates XML, landscape aspect, height at reading width (at most 440 px) and minimum actual label size (at least 14 px). It regenerates `layout-metrics.json` as well as the SVGs. Do not hand-edit SVGs or claim the size checks replace visual inspection.

The verified Linux-amd64 D2 v0.9.0 archive used by the [successful rendering run](https://github.com/yongkyuns/nxrs/actions/runs/37014223427) had SHA-256 `5669ddc46b99e942cc96078f4a4e36d5e62103348f4c05179ede27802fdd87a9`. Other platforms need their own official binary/checksum, not this Linux checksum.

[Return to the analysis](../README.md) · [nxrs implications](../nxrs-design-notes.md) · [Source evidence](../sources.md)
