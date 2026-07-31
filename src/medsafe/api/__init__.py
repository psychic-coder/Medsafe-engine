"""FastAPI service layer.

HTTP surface of the engine: ``main`` builds the app, ``routes`` holds the endpoint modules, and
``schemas`` defines the Pydantic v2 request/response contracts. This layer composes results from
``resolution``, ``pricing``, and ``safety`` — it contains no matching or scoring logic of its own.

# TODO: implement in Phase 5
"""
