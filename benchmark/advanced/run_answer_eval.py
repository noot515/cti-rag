"""Answer/citation evaluation wrapper with explicit model/judge availability gates."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from benchmark.advanced.report import MetricResult, MetricStatus
from benchmark.advanced.run_retrieval_eval import (
    _atomic_text,
    _write_json,
    run_retrieval_evaluation,
)


def _unavailable(reason: str) -> dict[str, Any]:
    return MetricResult(
        status=MetricStatus.NOT_RUN,
        reason=reason,
        support_count=0,
        annotation_coverage=0.0,
        value=None,
    ).model_dump(mode="json")


def run_answer_evaluation(
    *,
    config_path: Path,
    output: Path,
    allow_model_egress: bool = False,
    generator_model: str | None = None,
    judge_model: str | None = None,
) -> dict[str, Any]:
    """Produce a complete report without inventing generator/judge results.

    This phase ships no default generator/judge adapter. Permission plus an exact
    model identifier are prerequisites for any later adapter. Authorization is
    validated before even the retrieval report is executed so a malformed model
    request cannot trigger unrelated work first.
    """
    if allow_model_egress and not generator_model:
        raise ValueError("model egress permission requires an exact --generator-model")
    if generator_model and not allow_model_egress:
        raise ValueError("generator model use requires explicit --allow-model-egress")
    if judge_model and not allow_model_egress:
        raise ValueError("judge model use requires explicit --allow-model-egress")

    retrieval_summary = run_retrieval_evaluation(
        config_path=config_path,
        output=output,
    )

    generator_reason = (
        "no generator adapter/model configured; answer-quality evaluation was not run"
        if not generator_model
        else (
            "generator model was named but this offline fixture runner has no configured "
            "authorized generator adapter"
        )
    )
    judge_reason = (
        "no independent judge adapter/model configured; citation support was not run"
        if not judge_model
        else (
            "judge model was named but this offline fixture runner has no configured "
            "authorized judge adapter"
        )
    )

    answer_metrics = {
        "answer_quality": _unavailable(generator_reason),
        "citation_validity": _unavailable(
            "no generated response citations are available for validity checking"
        ),
        "citation_support": _unavailable(judge_reason),
        "abstention": _unavailable(
            "answer-generation adapter unavailable; abstention behavior not observed"
        ),
        "false_evidence_rate": _unavailable(
            "answer-generation adapter unavailable; unanswerable response behavior not observed"
        ),
        "real_quality_promotion": _unavailable(
            "synthetic fixture and unavailable generator/judge cannot authorize quality promotion"
        ),
        "model_egress_authorized": bool(allow_model_egress),
        "generator_model": generator_model,
        "judge_model": judge_model,
    }
    _write_json(output / "answer_metrics.json", answer_metrics)

    report_path = output / "report.md"
    existing = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    appendix = [
        "",
        "## Answer and citation evaluation",
        "",
        "- answer generation: not_run",
        "- citation validity: not_run (no emitted generated citations)",
        "- independent citation support: not_run",
        "- abstention / false-evidence behavior: not_run",
        "- model/judge egress: "
        + ("authorized but no adapter configured" if allow_model_egress else "not authorized"),
        "- real quality promotion: not_run",
        "",
        "Citation validity and claim support remain separate metrics; neither is inferred from the other.",
    ]
    _atomic_text(
        report_path,
        existing.rstrip() + "\n" + "\n".join(appendix) + "\n",
    )
    return {
        "schema_version": "advanced-answer-eval-report-v1",
        "output": str(output),
        "retrieval_queries": retrieval_summary["queries"],
        "answer_quality": "not_run",
        "citation_support": "not_run",
        "real_quality": "not_run",
        "network_used": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run advanced answer/citation evaluation"
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--allow-model-egress", action="store_true")
    parser.add_argument("--generator-model")
    parser.add_argument("--judge-model")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_answer_evaluation(
        config_path=args.config,
        output=args.output,
        allow_model_egress=args.allow_model_egress,
        generator_model=args.generator_model,
        judge_model=args.judge_model,
    )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
