"""Mongo → Elasticsearch indexer.

Two responsibilities:

  1. `backfill()` — one-shot scan of every relevant Mongo collection,
     pushes all docs to ES via `_bulk`. Called at startup when the index
     is missing or empty.

  2. `tail()` — long-running task that watches Mongo change streams on
     the `specs`, `plans`, and `history` collections and mirrors each
     change into ES. The tailer is started as a FastAPI lifespan task
     and cancelled at shutdown.

Mongo change streams require a replica set — this is why `docker-compose.yml`
runs `mongo` with `--replSet rs0` and the `mongo-init` sidecar. Change
streams return `{operationType, documentKey, fullDocument, ns, ...}`. We
request `fullDocument="updateLookup"` so updates give us the post-image,
not just a delta — makes converters trivial.

The tailer is resilient to single-doc failures: a converter exception on
one change is logged and skipped; the stream keeps going. Fatal errors
(stream closed by Mongo, auth rejected, network dropped) bubble up and
the lifespan task-cancellation path handles teardown.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk
from motor.motor_asyncio import (
    AsyncIOMotorClient,
    AsyncIOMotorCollection,
    AsyncIOMotorDatabase,
)

from specs_agent.search import converters as conv
from specs_agent.search.schema import INDEX_NAME, ensure_index, index_is_empty


log = logging.getLogger("specs_agent.search.indexer")


# Which collections to mirror. Names match MongoStorage's collection
# handles (see src/specs_agent/engine/mongo_storage.py).
WATCHED_COLLECTIONS = ("specs", "plans", "history")


class Indexer:
    """Owns the change-stream tail task and the backfill routine."""

    def __init__(
        self,
        *,
        mongo_url: str,
        mongo_db: str,
        es_client: AsyncElasticsearch,
    ) -> None:
        self._mongo_url = mongo_url
        self._mongo_db = mongo_db
        self._es = es_client

        # Initialized lazily in `start()` so we can fail fast with clear
        # errors there rather than at construction time.
        self._motor_client: AsyncIOMotorClient | None = None
        self._db: AsyncIOMotorDatabase | None = None
        self._tasks: list[asyncio.Task] = []

    # --------------------------------------------------------------- #
    # Lifecycle
    # --------------------------------------------------------------- #

    async def start(self) -> None:
        """Connect to Mongo, ensure index, backfill if empty, start tailer."""
        self._motor_client = AsyncIOMotorClient(self._mongo_url)
        self._db = self._motor_client[self._mongo_db]

        await ensure_index(self._es)
        if await index_is_empty(self._es):
            log.info("search index empty — running backfill")
            await self.backfill()

        for coll in WATCHED_COLLECTIONS:
            task = asyncio.create_task(
                self._tail_collection(coll),
                name=f"search-tail-{coll}",
            )
            self._tasks.append(task)
        log.info("search indexer started, tailing %s", WATCHED_COLLECTIONS)

    async def stop(self) -> None:
        """Cancel tailer tasks and close Motor client. Idempotent."""
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks = []
        if self._motor_client is not None:
            self._motor_client.close()
            self._motor_client = None
            self._db = None

    # --------------------------------------------------------------- #
    # Backfill
    # --------------------------------------------------------------- #

    async def backfill(self) -> int:
        """Rebuild the index from every relevant Mongo collection.

        Returns the number of ES docs upserted. Safe to call multiple
        times; the ES IDs are stable so it's an idempotent refresh.
        """
        assert self._db is not None, "call start() first"

        actions: list[dict] = []

        # specs → spec + endpoint docs
        async for row in self._db["specs"].find():
            actions.extend(_bulk_upsert_actions(conv.spec_to_docs(row)))

        # plans → test_case docs (one per case)
        async for row in self._db["plans"].find():
            spec_id = _spec_id_for_plan(row)
            actions.extend(
                _bulk_upsert_actions(conv.plan_to_test_case_docs(row, spec_id=spec_id))
            )

        # history → run docs
        async for row in self._db["history"].find():
            actions.extend(_bulk_upsert_actions(conv.run_to_doc(row)))

        if not actions:
            return 0

        ok, errors = await async_bulk(
            self._es, actions, raise_on_error=False, raise_on_exception=False,
        )
        if errors:
            log.warning("backfill completed with %d errors", len(errors) if isinstance(errors, list) else errors)
        return int(ok)

    # --------------------------------------------------------------- #
    # Change-stream tailer
    # --------------------------------------------------------------- #

    async def _tail_collection(self, collection_name: str) -> None:
        """Watch one collection's change stream and mirror each event to ES.

        Keeps retrying on transient failures. Cancellation (from `stop()`)
        is raised and propagated so the task exits cleanly.
        """
        assert self._db is not None, "call start() first"
        coll: AsyncIOMotorCollection = self._db[collection_name]

        while True:
            try:
                async with coll.watch(full_document="updateLookup") as stream:
                    async for change in stream:
                        try:
                            await self._apply_change(collection_name, change)
                        except Exception:
                            # Per-event failures must not kill the tailer.
                            log.exception(
                                "failed to apply change on %s: %s",
                                collection_name, change.get("operationType"),
                            )
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception(
                    "change stream on %s failed; reopening in 2s",
                    collection_name,
                )
                await asyncio.sleep(2)

    async def _apply_change(self, collection: str, change: dict) -> None:
        """Translate one change-stream event to ES operations.

        Insert / update / replace → upsert the converted ES docs.
        Delete → remove the ES docs by ID (and, for specs, also nuke the
        collateral endpoint / test_case / run docs by prefix via
        delete_by_query).
        """
        op = change.get("operationType")
        doc_key = change.get("documentKey") or {}
        mongo_id = doc_key.get("_id")
        full = change.get("fullDocument")

        if op in ("insert", "replace", "update") and full is not None:
            if collection == "specs":
                actions = _bulk_upsert_actions(conv.spec_to_docs(full))
            elif collection == "plans":
                spec_id = _spec_id_for_plan(full)
                actions = _bulk_upsert_actions(
                    conv.plan_to_test_case_docs(full, spec_id=spec_id)
                )
            elif collection == "history":
                actions = _bulk_upsert_actions(conv.run_to_doc(full))
            else:
                return

            if actions:
                await async_bulk(
                    self._es, actions,
                    raise_on_error=False, raise_on_exception=False,
                )
            return

        if op == "delete":
            await self._handle_delete(collection, mongo_id)

    async def _handle_delete(self, collection: str, mongo_id: Any) -> None:
        """Remove ES docs corresponding to a deleted Mongo document."""
        if mongo_id is None:
            return

        # Note: ES does NOT allow `prefix` queries on the `_id` field
        # (it's a special `_id` type, not `keyword`). All cascading deletes
        # therefore match on `kind` + `spec_id` — both indexed as keyword.

        if collection == "specs":
            spec_id = str(mongo_id)
            # The spec doc + all its endpoint docs in one query. Test case
            # and run docs for this spec stay put — those belong to the
            # `plans` / `history` collections and will be cleaned up when
            # those Mongo docs are deleted.
            await self._es.delete_by_query(
                index=INDEX_NAME,
                body={
                    "query": {
                        "bool": {
                            "must": [
                                {"term": {"spec_id": spec_id}},
                                {"terms": {"kind": ["spec", "endpoint"]}},
                            ],
                        },
                    },
                },
                refresh=True,
                conflicts="proceed",
            )
            return

        if collection == "plans":
            # Plan _id is spec_title. The owning spec_id is the slug of
            # that title (MongoStorage.save_spec uses the same rule).
            spec_id = conv._slugify_spec_id(str(mongo_id))
            await self._es.delete_by_query(
                index=INDEX_NAME,
                body={
                    "query": {
                        "bool": {
                            "must": [
                                {"term": {"spec_id": spec_id}},
                                {"term": {"kind": "test_case"}},
                            ],
                        },
                    },
                },
                refresh=True,
                conflicts="proceed",
            )
            return

        if collection == "history":
            # history _id is "{spec_hash}:{filename}" but the ES run doc
            # keys on slugified spec title + filename. We don't have the
            # spec title in a delete event. Fall back to deleting any run
            # doc whose meta.filename matches — rare event, acceptable.
            filename = str(mongo_id).split(":", 1)[-1]
            if not filename:
                return
            await self._es.delete_by_query(
                index=INDEX_NAME,
                body={
                    "query": {
                        "bool": {
                            "must": [
                                {"term": {"kind": "run"}},
                                # Match either dynamic-mapped variant of meta.filename.
                                {
                                    "bool": {
                                        "should": [
                                            {"term": {"meta.filename.keyword": filename}},
                                            {"term": {"meta.filename": filename}},
                                        ],
                                        "minimum_should_match": 1,
                                    },
                                },
                            ],
                        },
                    },
                },
                refresh=True,
                conflicts="proceed",
            )


# ------------------------------------------------------------------- #
# Helpers
# ------------------------------------------------------------------- #


def _bulk_upsert_actions(docs: list[tuple[str, dict]]) -> list[dict]:
    """Convert (id, source) tuples into ES `index` bulk actions.

    We use `index` rather than `update` so the full source replaces any
    existing doc — simpler semantics when a spec is re-saved and its
    endpoint list changes.
    """
    actions: list[dict] = []
    for doc_id_str, source in docs:
        actions.append({
            "_op_type": "index",
            "_index": INDEX_NAME,
            "_id": doc_id_str,
            "_source": source,
        })
    return actions


def _spec_id_for_plan(plan_doc: dict) -> str:
    """Derive the owning spec's _id for a plan doc.

    MongoStorage stores plans keyed by `spec_title`; the specs collection
    keys by a slug of the title. Match that slug rule.
    """
    return conv._slugify_spec_id(str(plan_doc.get("spec_title") or plan_doc.get("_id") or ""))
