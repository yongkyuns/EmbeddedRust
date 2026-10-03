# PX4 execution diagrams: spacing-balanced layout

This revision keeps **0794f41d** as the rollback point and changes only the first two primary diagrams. The third four-loop map is unchanged.

The architecture and visual language are preserved: the same Hardware/NuttX band, A/B/C/D execution-context grouping, uORB strip, colors, module names and data/wakeup distinction remain. This pass improves **box sizing, position, gutters, vertical spacing, and connector routing together** instead of routing lines around a cramped layout.

- [Sensor-to-EKF execution map](sensor-to-ekf-execution-map.svg) · [D2](sensor-to-ekf-execution-map.d2)
- [Execution loops and data flow](execution-loops-data-flow.svg) · [D2](execution-loops-data-flow.d2)
- [Four-loop map — unchanged](execution-map.svg) · [D2](execution-map.d2)

## What changed from 0794f41d

### Sensor-to-EKF map

- worker cards are about 8% wider; inner boxes gain similar width/height
- worker-to-worker gutter increases from 24 to 34 px
- worker/uORB vertical separation increases from 16 to 34 px
- uORB topic spacing increases from 16 to 22 px
- hardware spacing and bottom legend spacing are slightly increased
- all 19 connectors are re-routed orthogonally through the enlarged gaps

The rendered canvas moves from 1939 × 1527 to about **2089 × 1626**: a modest increase that materially reduces congestion.

### Execution loops and data flow

- execution-context gutters increase from 14 to 28 px
- module gutters increase from 10 to 18 px
- topic gutters increase from 10 to 18 px
- layer spacing increases from 10 to 18 px
- execution/module/topic cards are widened and slightly taller
- all 28 connectors are re-routed through the larger inter-layer corridors

The canvas moves from 2784 × 1544 to about **3234 × 1627**. The extra width is intentional: this is a dense full-page ownership/data-flow reference and benefits more from readable columns than from compactness.

## Routing model

D2 remains the source of graph topology, block geometry and styling. `routes.json` specifies orthogonal connector waypoints and label placement for the first two diagrams; `route_svg.py` snaps those lanes to D2's rendered source/target boundaries and applies them after the D2 render.

The routing pass verifies that every configured signal edge exists, its label text is unchanged, and no routed connector centerline crosses a visible leaf-box interior.

## Reproduce

Requires D2 **v0.9.0**, Bash and Python 3.9+:

```sh
bash docs/references/px4/diagrams/render.sh
```

The first two diagrams are full-page references. Their documented standalone reading widths are 2100 and 3300 px. The third map keeps its 1000 px reading-width gate; the nine compact panels retain 800 px and the two supplemental traces retain 1200 px.

[Return to the analysis](../README.md)
