"""Request-scoped advanced retrieval orchestration with bounded degradation."""
from __future__ import annotations

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
import inspect
import threading
import time
from typing import Any, Callable, Mapping, Protocol

from packages.evidence.ids import canonical_hash
from packages.evidence.policy import Principal, ResolvedScope
from packages.evidence.schema import ObjectCandidate, RetrievalRequest, RetrievalResult, SnapshotRef
from packages.retrieval.candidate import ChannelResult
from packages.retrieval.fusion import FusionOutcome, fuse_channel_results
from packages.retrieval.planner import DeterministicQueryPlanner, QueryPlan


class RetrievalUnavailable(RuntimeError):
    pass


class ChannelBackendError(RuntimeError):
    """Expected backend outage that can degrade without hiding catalog/policy failures."""


class QueueSaturated(RuntimeError):
    pass


class RetrievalChannel(Protocol):
    name: str

    def search(
        self,
        plan: QueryPlan,
        scope: ResolvedScope,
        snapshot: SnapshotRef,
        deadline: float,
    ) -> ChannelResult: ...


class SnapshotHandleLike(Protocol):
    manifest: Any

    @property
    def snapshot(self) -> SnapshotRef: ...

    def __enter__(self): ...
    def __exit__(self, *args): ...


class SnapshotManagerLike(Protocol):
    def pin_active(self, scope: ResolvedScope) -> SnapshotHandleLike: ...


class BoundedExecutor:
    """Thread pool with a hard bound on running plus queued work."""

    def __init__(self, *, max_workers: int = 3, queue_capacity: int = 2) -> None:
        if max_workers < 1 or queue_capacity < 0:
            raise ValueError("invalid bounded executor capacity")
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="advanced-retrieval",
        )
        self._permits = threading.BoundedSemaphore(max_workers + queue_capacity)

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
        if not self._permits.acquire(blocking=False):
            raise QueueSaturated("bounded retrieval executor queue is saturated")
        try:
            future = self._pool.submit(fn, *args, **kwargs)
        except Exception:
            self._permits.release()
            raise
        future.add_done_callback(lambda _: self._permits.release())
        return future

    def shutdown(self, *, wait: bool = False) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=True)


@dataclass(frozen=True)
class ChannelExecution:
    result: ChannelResult
    elapsed_ms: float


@dataclass(frozen=True)
class RetrievalExecution:
    request: RetrievalRequest
    started_at: float
    deadline: float
    scope: ResolvedScope
    snapshot: SnapshotRef
    plan: QueryPlan
    channel_results: tuple[ChannelResult, ...]
    fusion: FusionOutcome
    status: str
    truncated: bool
    timings_ms: dict[str, float]
    authorized_trace: tuple[str, ...]


class AdvancedRetrievalOrchestrator:
    """Resolve authority/snapshot once, execute channels, then fuse deterministically."""

    def __init__(
        self,
        *,
        policy: Any,
        snapshot_manager: SnapshotManagerLike,
        planner: DeterministicQueryPlanner,
        channels: Mapping[str, RetrievalChannel],
        total_timeout_seconds: float = 10.0,
        channel_timeout_seconds: float = 3.0,
        pre_rerank_limit: int = 60,
        clock: Callable[[], float] = time.monotonic,
        executor_factory: Callable[[], BoundedExecutor] | None = None,
        reranker: Any | None = None,
    ) -> None:
        if total_timeout_seconds <= 0 or channel_timeout_seconds <= 0:
            raise ValueError("retrieval deadlines must be positive")
        if pre_rerank_limit < 1 or pre_rerank_limit > 60:
            raise ValueError("pre_rerank_limit must be between 1 and 60")
        unknown = set(channels) - {"exact", "lexical", "dense", "graph"}
        if unknown:
            raise ValueError(f"unsupported advanced retrieval channels: {sorted(unknown)}")
        self.policy = policy
        self.snapshot_manager = snapshot_manager
        self.planner = planner
        self.channels = dict(channels)
        self.total_timeout_seconds = total_timeout_seconds
        self.channel_timeout_seconds = channel_timeout_seconds
        self.pre_rerank_limit = pre_rerank_limit
        self.clock = clock
        self.reranker = reranker
        factory = executor_factory or (
            lambda: BoundedExecutor(max_workers=3, queue_capacity=2)
        )
        # One bounded executor is shared by requests handled by this orchestrator.
        # A timed-out running call therefore continues to occupy a permit until it
        # actually exits instead of escaping into an unbounded sequence of pools.
        self._executor = factory()

    def close(self, *, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait)

    def _invoke_channel(
        self,
        channel: RetrievalChannel,
        plan: QueryPlan,
        scope: ResolvedScope,
        snapshot: SnapshotRef,
        deadline: float,
    ) -> ChannelExecution:
        started = self.clock()
        try:
            value = channel.search(plan, scope, snapshot, deadline)
            if inspect.isawaitable(value):
                value = asyncio.run(value)
            if not isinstance(value, ChannelResult):
                raise TypeError("retrieval channel returned a non-ChannelResult value")
            if value.channel != channel.name:
                raise ValueError("channel result name mismatch")
            if value.status == "ok" and not value.candidates:
                value = value.model_copy(update={"status": "no_results"})
            return ChannelExecution(
                value,
                max(0.0, (self.clock() - started) * 1000.0),
            )
        except TimeoutError:
            return ChannelExecution(
                ChannelResult(
                    channel=channel.name,
                    status="timeout",
                    reason="deadline",
                ),
                max(0.0, (self.clock() - started) * 1000.0),
            )
        except ChannelBackendError:
            return ChannelExecution(
                ChannelResult(
                    channel=channel.name,
                    status="error",
                    reason="backend-unavailable",
                ),
                max(0.0, (self.clock() - started) * 1000.0),
            )

    def _submit(
        self,
        channel: RetrievalChannel,
        plan: QueryPlan,
        scope: ResolvedScope,
        snapshot: SnapshotRef,
        total_deadline: float,
    ) -> tuple[Future | None, float, ChannelExecution | None]:
        deadline = min(total_deadline, self.clock() + self.channel_timeout_seconds)
        try:
            future = self._executor.submit(
                self._invoke_channel,
                channel,
                plan,
                scope,
                snapshot,
                deadline,
            )
            return future, deadline, None
        except QueueSaturated:
            return (
                None,
                deadline,
                ChannelExecution(
                    ChannelResult(
                        channel=channel.name,
                        status="error",
                        reason="queue-saturated",
                    ),
                    0.0,
                ),
            )

    def _collect(
        self,
        channel_name: str,
        future: Future | None,
        deadline: float,
        immediate: ChannelExecution | None,
    ) -> ChannelExecution:
        if immediate is not None:
            return immediate
        assert future is not None
        remaining = max(0.0, deadline - self.clock())
        try:
            return future.result(timeout=remaining)
        except FutureTimeout:
            future.cancel()
            return ChannelExecution(
                ChannelResult(
                    channel=channel_name,
                    status="timeout",
                    reason="deadline",
                ),
                self.channel_timeout_seconds * 1000.0,
            )

    @staticmethod
    def _trace(result: ChannelResult) -> str:
        return (
            f"channel={result.channel};status={result.status};"
            f"count={len(result.candidates)};"
            f"truncated={str(result.truncated).lower()}"
        )

    @staticmethod
    def _seed_ids(result: ChannelResult | None) -> tuple[str, ...]:
        if result is None:
            return ()
        return tuple(
            dict.fromkeys(
                candidate.object_uid
                for candidate in result.candidates
                if isinstance(candidate, ObjectCandidate)
            )
        )[:8]

    @staticmethod
    def _is_degraded(result: ChannelResult) -> bool:
        if result.status in {"timeout", "error"}:
            return True
        return result.status == "not_run" and result.reason == "not-configured"

    def _initial_plan(self, request: RetrievalRequest) -> QueryPlan:
        return self.planner.plan(
            request.query,
            max_graph_hops=request.max_graph_hops,
            top_k=request.top_k,
            lexical_enabled="lexical" in self.channels,
            dense_enabled="dense" in self.channels,
        )

    def retrieve_candidates(
        self,
        request: RetrievalRequest,
        trusted_principal: Principal,
    ) -> RetrievalExecution:
        scope = self.policy.resolve_scope(trusted_principal, request.corpus_id)
        total_started = self.clock()
        total_deadline = total_started + self.total_timeout_seconds
        with self.snapshot_manager.pin_active(scope) as handle:
            snapshot = handle.snapshot
            plan = self._initial_plan(request)
            executions: dict[str, ChannelExecution] = {}
            submitted: dict[
                str,
                tuple[Future | None, float, ChannelExecution | None],
            ] = {}
            for name, enabled in (
                ("exact", plan.exact_enabled),
                ("lexical", plan.lexical_enabled),
                ("dense", plan.dense_enabled),
            ):
                if not enabled:
                    continue
                channel = self.channels.get(name)
                if channel is None:
                    executions[name] = ChannelExecution(
                        ChannelResult(
                            channel=name,
                            status="not_run",
                            reason="not-configured",
                        ),
                        0.0,
                    )
                    continue
                submitted[name] = self._submit(
                    channel,
                    plan,
                    scope,
                    snapshot,
                    total_deadline,
                )

            # Exact is collected first only because graph depends on authorized
            # deterministic seed evidence. Lexical/dense continue independently.
            if "exact" in submitted:
                executions["exact"] = self._collect(
                    "exact",
                    *submitted.pop("exact"),
                )

            seed_ids = self._seed_ids(
                executions.get("exact").result
                if "exact" in executions
                else None
            )
            graph_plan = self.planner.plan(
                request.query,
                authorized_seed_ids=seed_ids,
                max_graph_hops=request.max_graph_hops,
                top_k=request.top_k,
                lexical_enabled="lexical" in self.channels,
                dense_enabled="dense" in self.channels,
            )
            if graph_plan.graph_enabled:
                channel = self.channels.get("graph")
                if channel is None:
                    executions["graph"] = ChannelExecution(
                        ChannelResult(
                            channel="graph",
                            status="not_run",
                            reason="not-configured",
                        ),
                        0.0,
                    )
                else:
                    submitted["graph"] = self._submit(
                        channel,
                        graph_plan,
                        scope,
                        snapshot,
                        total_deadline,
                    )
            elif "graph" in self.channels:
                executions["graph"] = ChannelExecution(
                    ChannelResult(
                        channel="graph",
                        status="not_run",
                        reason="plan-disabled",
                    ),
                    0.0,
                )

            for name in sorted(submitted):
                executions[name] = self._collect(
                    name,
                    *submitted[name],
                )

            ordered_results = tuple(
                executions[name].result for name in sorted(executions)
            )
            if not ordered_results:
                raise RetrievalUnavailable(
                    "no configured channel is usable for this plan"
                )
            usable = [
                result
                for result in ordered_results
                if result.status in {"ok", "no_results"}
                or bool(result.candidates)
            ]
            failures = [
                result for result in ordered_results if self._is_degraded(result)
            ]
            if not usable:
                raise RetrievalUnavailable(
                    "no usable configured retrieval channel"
                )

            final_plan = graph_plan
            fusion = fuse_channel_results(
                ordered_results,
                plan=final_plan,
                limit=self.pre_rerank_limit,
            )
            if fusion.candidates:
                status = "partial" if failures else "ok"
            else:
                status = "partial" if failures else "no_evidence"
            truncated = any(
                result.truncated or result.status == "timeout"
                for result in ordered_results
            )
            timings = {
                name: execution.elapsed_ms
                for name, execution in sorted(executions.items())
            }
            timings["total"] = max(
                0.0,
                (self.clock() - total_started) * 1000.0,
            )
            trace = tuple(self._trace(result) for result in ordered_results)
            return RetrievalExecution(
                request=request,
                started_at=total_started,
                deadline=total_deadline,
                scope=scope,
                snapshot=snapshot,
                plan=final_plan,
                channel_results=ordered_results,
                fusion=fusion,
                status=status,
                truncated=truncated,
                timings_ms=timings,
                authorized_trace=trace,
            )

    def retrieve(
        self,
        request: RetrievalRequest,
        trusted_principal: Principal,
    ) -> RetrievalResult:
        execution = self.retrieve_candidates(request, trusted_principal)
        candidates = execution.fusion.candidates
        trace = list(execution.authorized_trace)
        timings = dict(execution.timings_ms)
        model_fingerprints: dict[str, str] = {}
        status = execution.status

        if self.reranker is None:
            trace.append("reranker=status=not_configured")
        elif candidates:
            started = self.clock()
            outcome = self.reranker.rerank(
                request.query,
                candidates,
                scope=execution.scope,
                snapshot=execution.snapshot,
                exact_priority_candidate_ids=(
                    execution.fusion.exact_priority_candidate_ids
                ),
                request_deadline=execution.deadline,
            )
            timings["reranker"] = max(
                0.0,
                (self.clock() - started) * 1000.0,
            )
            candidates = outcome.candidates
            safe_reason = f";reason={outcome.reason}" if outcome.reason else ""
            trace.append(f"reranker=status={outcome.status}{safe_reason}")
            if outcome.model_fingerprint:
                model_fingerprints["reranker"] = outcome.model_fingerprint
            if outcome.status == "unavailable" and status == "ok":
                status = "partial"
        else:
            trace.append("reranker=status=not_run")

        timings["total"] = max(
            0.0,
            (self.clock() - execution.started_at) * 1000.0,
        )
        selected = candidates[: request.top_k]
        output_truncated = (
            execution.truncated or len(candidates) > len(selected)
        )
        run_id = canonical_hash(
            [
                "advanced-retrieval-run-v1",
                execution.snapshot.snapshot_id,
                execution.request.query,
                execution.request.corpus_id,
                execution.request.top_k,
            ]
        )
        return RetrievalResult(
            retrieval_run_id=run_id,
            domain=execution.scope.domain,
            snapshot=execution.snapshot,
            status=status,
            candidates=selected,
            answer_context="",
            citations=(),
            authorized_trace=tuple(trace),
            truncated=output_truncated,
            timings_ms=timings,
            model_fingerprints=model_fingerprints,
        )


__all__ = [
    "AdvancedRetrievalOrchestrator",
    "BoundedExecutor",
    "ChannelBackendError",
    "QueueSaturated",
    "RetrievalExecution",
    "RetrievalUnavailable",
]
