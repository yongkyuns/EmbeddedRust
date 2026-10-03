# PX4 execution diagrams: aligned blocks and explicit routing

All three primary maps were revised together. The starting point for this pass is
**4a61eb13**; the earlier **0794f41d** remains available in the PR history.

- [Sensor-to-EKF execution map](sensor-to-ekf-execution-map.svg) · [D2](sensor-to-ekf-execution-map.d2)
- [Execution loops and data flow](execution-loops-data-flow.svg) · [D2](execution-loops-data-flow.d2)
- [Four-loop interaction map](execution-map.svg) · [D2](execution-map.d2)

## Layout changes

The sensor-to-EKF map uses four equal-width execution cards, a dedicated IRQ/UART
entry-label band, and separate topic-routing lanes. Topic order follows the
consumers more closely. The uORB caption sits below the wiring rather than in its
path. Data and scheduling arrows use distinct boundary attachment points.

The broader execution map aligns workers with the modules they execute. INS0 and
navigation worker cards span their two module columns. Explicit invisible spacer
cells replace oversized grid gaps, which had also expanded the outside padding.
Scheduler fan-out, same-thread ownership, and topic traffic occupy separate
corridors. Labels sit beside or above connectors, not on them.

The four-loop map keeps its independent IMU and GNSS paths, but places labels
above straight transfers. Data/wake pairs remain parallel and distinct. Body
text is no longer uniformly bold. Two opaque explanatory-label panels interrupt
only decorative lifelines; they do not hide signal arrows.

| Diagram | Previous canvas | Revised canvas | Standalone reading width |
| --- | --- | --- | --- |
| Sensor-to-EKF | 2089 × 1626 | 1854 × 1573 | 1600 px |
| Execution loops/data flow | 3234 × 1627 | 2200 × 1695 | 1800 px |
| Four-loop interactions | 1654 × 1186 | 1654 × 1331 | 1000 px |

The first two use less total canvas area. The third deliberately uses additional
vertical room to keep full-size labels off the paired arrows. These are detailed
reference maps, not 800 px thumbnails. `layout-metrics.json` reports both thumbnail
metrics and the documented reading widths; every diagram has at least 14 px text
at its reading width. The nine compact panels still use 800 px and the two
supplemental traces use 1200 px. All eleven non-primary SVGs are unchanged.

## Semantics retained

The Hardware/NuttX responsibility band, A/B/C/D thread ownership, module identities,
uORB storage, and data-versus-wakeup distinction are retained. A flat build is
still one shared address space, not a protected user/kernel split. In the shown
path GNSS does not wake EKF2; EKF2 reads it during an IMU-driven run. No firmware,
HAL, scheduler implementation, or runtime dependency is changed by this pass.

## Routing and validation

D2 is the source of topology, blocks, labels, and styling. `routes.json` contains
editable orthogonal waypoints and label positions for all three primary maps.
`route_svg.py` uses explicit ports on each declared source/target boundary rather
than inheriting unsuitable endpoints from ELK's grid routing. It does not move
nodes. Short white underlays distinguish wire crossings from junctions.

The renderer is pinned to **D2 v0.9.0**. Raw SVG hashes fail closed when a source or
renderer changes; review the affected routes and refresh their raw hashes only
after inspecting the new rendering. The routing pass verifies all **65 connectors**
(19 + 28 + 18, including five decorative lifelines), their **130 boundary endpoints**,
unchanged arrow markers and label wording, unchanged node groups, and no visible
leaf-block interior intersections or shared collinear signal segments.

The maps are not claimed to be planar: the two dense maps have 9 and 11 strict
signal-wire crossings; the four-loop map has none. The distinction is explicit in
`routing-checks.json`. The browser check separately measures actual text bounds
with D2's embedded fonts, checking node-label containment, text/text overlap, and
text/signal-arrow clearance. It verifies the two masked decorative-lifeline
intersections instead of treating them as hidden signal intersections.

## Reproduce

Requires D2 **v0.9.0**, Bash and Python 3.9+:

```sh
bash docs/references/px4/diagrams/render.sh
```

This renders all 14 SVGs, applies the three routing plans, checks geometry and
readability, and runs five standard-library regression tests.

For optional browser qualification and PNG previews:

```sh
python3 -m pip install playwright
python3 -m playwright install chromium
python3 docs/references/px4/diagrams/check_browser.py --screenshots-dir /tmp/px4-previews
```

Use `--chromium /path/to/chromium` to select an installed browser. The result is
recorded in `browser-checks.json` with the browser version. This browser dependency
is only for documentation validation, not a firmware dependency.

[Return to the analysis](../README.md)
