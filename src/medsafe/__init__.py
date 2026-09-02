"""medsafe — generic medicine substitute and prescription safety engine.

Top-level package. Holds only the package version; all behaviour lives in the subpackages:
``graph`` (Neo4j schema and access), ``resolution`` (normalization and matching), ``pricing``
(substitution and savings), ``safety`` (interaction lookup), ``api`` (FastAPI service), and
``eval`` (evaluation harness). The graph schema this package is built against is locked in
``docs/schema.md``.
"""

__version__ = "0.1.0"
