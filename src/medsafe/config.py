"""Application configuration.

Single source of truth for runtime settings, loaded from environment variables (and a local
``.env``) into a Pydantic v2 settings model: Neo4j connection details (URI, user, password,
database), API host/port/log level, the ``data/{raw,processed,manual}`` directory paths used by the
ingestion scripts, and entity-resolution tuning — the fuzzy *candidate* threshold and the path to
``fuzzy_negative_blocklist.csv``. The fuzzy threshold governs which pairs enter the human-review
queue only; it is never an auto-accept threshold (see ``docs/schema.md``). Every other module reads
configuration from here rather than touching ``os.environ`` directly.

# TODO: implement in Phase 1
"""
