"""``/health`` — liveness and readiness.

Liveness returns process health without touching the database. Readiness verifies the Neo4j driver
can execute a trivial query and that the expected constraints and node counts exist, so an API
running against an empty or unloaded graph reports unready rather than answering queries with
misleading empty results. Used by the docker-compose healthcheck and any upstream probe.

# TODO: implement in Phase 5
"""
