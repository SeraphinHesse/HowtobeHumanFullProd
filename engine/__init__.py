"""How To Be Human pseudo-engine.

Packages: coords (coordinate authority), render (RenderItem pipeline),
assets (slot resolution + placeholder), core / physics (later phases),
data_io (schema-validating JSON load/write).

Import boundary: pygame is allowed ONLY in engine.render.backend and
engine.assets' surface-side modules (placeholder, store). Everything else
stays pure Python and headless-testable.
"""
