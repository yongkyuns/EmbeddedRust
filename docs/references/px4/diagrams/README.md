# Original design, connector-only routing

The three main D2 sources are restored byte-for-byte from **3079e378**, before the rejected full relayout. The worker boxes, bands, nested groups, node text, colors, sizes and positions are not redesigned.

- [Sensor-to-EKF execution map](sensor-to-ekf-execution-map.svg) · [D2](sensor-to-ekf-execution-map.d2)
- [Execution loops and data flow](execution-loops-data-flow.svg) · [D2](execution-loops-data-flow.d2)
- [Four-loop map](execution-map.svg) · [D2](execution-map.d2)

The first two maps have 19 and 28 connectors respectively rerouted through existing margins and gutters. Connection text is repositioned/reflowed without changing its wording. Their 38 and 36 node groups remain identical to D2's original render. The third map is restored unchanged: its original horizontal wiring did not need another redesign.

## Reproduce

Requires D2 **v0.9.0**, Bash and Python **3.9+** (standard library only):

```sh
bash docs/references/px4/diagrams/render.sh
```

**Important: the final first-two SVGs use a post-render routing pass.** Running `d2 file.d2 file.svg` alone reproduces the old straight grid connectors, not the revised wiring. D2 controls the graph, blocks and styling; `routes.json` specifies connector waypoints and label placement; `route_svg.py` applies those routes to the generated SVG. This is not claimed to be native D2 waypoint syntax.

This approach follows the requirement to preserve the old block geometry. [D2's grid documentation](https://d2lang.com/tour/grid-diagrams/#connections-between-grid-cells) explains that ELK/Dagre use center-to-center straight segments within grids without path-finding. Changing general layout parameters would not meet a strict geometry-preservation requirement.

The baseline raw SVG hashes are locked. A source edit that changes the baseline must be reviewed and its routes updated deliberately; the helper fails instead of silently applying stale coordinates. It also checks connector identifiers and label wording, exact node-group equality before/after, orthogonal waypoints, and centerline intersections with visible leaf-box interiors. Container backgrounds, intentional border crossings, stroke thickness, rounded elbows and wire-to-wire crossings are not a zero-collision certification. Visual inspection remains required.

## Reading widths

The original diagrams are dense full-page views. Open the SVG rather than reading a small thumbnail. The restored first, second and third maps use 1800, 2800 and 1000 px reading widths respectively; the two supplemental sensor traces use 1200 px. The original nine small panels retain 800 px. Actual sizes are recorded in `layout-metrics.json`; thumbnail text is not claimed readable.

## D2 skill used for review and validation

The public [d2-diagrams skill](https://github.com/khollingworth/d2-diagram-skill/tree/085cb0580b35d959d63ff39cc5186529b8124bbe/skills/d2-diagrams) supplies the render-and-inspect workflow. Validation can set `D2_SKILL_RENDER` to its reviewed `scripts/render.sh`; this runs its validation and ELK rendering with remote assets disabled before the routing-only pass. The temporary validation workflow pins and verifies the skill scripts. No skill is installed into the application, and no separate Codex agent execution is claimed.

[Return to the analysis](../README.md)
