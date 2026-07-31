"""FastAPI application factory and entry point.

Constructs the ``app``, wires configuration from ``medsafe.config``, manages the Neo4j driver over
the application lifespan (open on startup, close on shutdown), registers the ``resolve``, ``check``,
and ``health`` routers, and installs exception handlers so a resolution failure or an unavailable
graph returns a structured error rather than a bare 500. Served by uvicorn as
``medsafe.api.main:app``.

# TODO: implement in Phase 5
"""
