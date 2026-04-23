"""Elasticsearch-backed search for specs, endpoints, test cases, and runs.

The API never writes to Elasticsearch directly. All writes go to MongoDB
(via `MongoStorage`); a change-stream tailer running in the FastAPI lifespan
reflects those writes into ES as denormalized documents. This keeps a single
source of truth and lets us rebuild the ES index at any time from Mongo.

Public surface:
    get_client()         — lazy singleton AsyncElasticsearch client
    close_client()       — shutdown hook
    search()             — query facade (see `service.py`)
    Indexer              — change-stream tailer + backfill (see `indexer.py`)
    ensure_index()       — create the index with mapping if missing
    reset_index()        — drop and recreate (schema migrations)
"""

from specs_agent.search.client import close_client, get_client
from specs_agent.search.indexer import Indexer
from specs_agent.search.schema import ensure_index, reset_index
from specs_agent.search.service import SearchResult, search

__all__ = [
    "Indexer",
    "SearchResult",
    "close_client",
    "ensure_index",
    "get_client",
    "reset_index",
    "search",
]
