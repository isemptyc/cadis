Cadis is a deterministic, dataset-driven runtime for country-level administrative hierarchy lookup.

It interprets pre-built country datasets and composes final hierarchy results according to dataset-declared policies. The runtime supports layered supplementation mechanisms (such as hierarchy completion or structural repair), with all behavior strictly defined by the dataset manifest.

Its runtime data model is compatible with common administrative representations (including those found in OpenStreetMap), supporting hierarchical levels and stable object identifiers (for example, `osm_id` or other feature IDs).

Cadis does not include or distribute OpenStreetMap data. Datasets are provided separately.

Cadis does not perform global country resolution or cross-country dispatch.
