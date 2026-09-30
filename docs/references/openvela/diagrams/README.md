# Reference diagrams

The OpenVela/nxrs comparison uses D2 source plus checked-in SVGs so GitHub can display the diagrams without an external rendering service.

| Source | Rendered diagram |
| --- | --- |
| [openvela-abstractions.d2](openvela-abstractions.d2) | [OpenVela device-class path](openvela-abstractions.svg) |
| [nxrs-capability-boundary.d2](nxrs-capability-boundary.d2) | [Nxrs capability/provider boundary](nxrs-capability-boundary.svg) |

## Material-style palette

Both sources import [material.d2](material.d2): a custom Material-style light palette with rounded shapes, blue application nodes, teal contracts, indigo implementations, amber platform adaptation, and neutral hardware/data sources. This is not a built-in theme named Material. D2 v0.9.0's [theme catalog](https://github.com/d2lang/d2/blob/v0.9.0/d2themes/d2themescatalog/catalog.go) does not contain that preset; the sources explicitly style nodes over base theme 0. See the official [D2 theme documentation](https://d2lang.com/tour/themes/).

## Reproduce

Install [D2 v0.9.0](https://github.com/d2lang/d2/releases/tag/v0.9.0), then run from the repository root:

```sh
d2 --version
bash docs/references/openvela/diagrams/render.sh
```

Alternatively, set `D2=/absolute/path/to/d2`. The script uses the ELK layout engine and emits both SVGs alongside their sources. Regenerate the SVGs whenever a diagram or the shared palette changes. Using another D2 version may change layout or serialization.

The SVGs were compiled with D2 v0.9.0, parsed as XML, and visually inspected in Chromium. The diagrams illustrate the boundaries discussed in the [reference note](../README.md); they do not claim all provider/target combinations are implemented or tested.
