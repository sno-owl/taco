from __future__ import annotations

import json
import operator
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any


OPS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}


@dataclass
class RuleResult:
    metric: str
    op: str
    expected: float
    actual: float | None
    passed: bool
    why: str
    fix: str


@dataclass
class SignatureResult:
    signature_id: str
    title: str
    severity: str
    description: str
    matched: bool
    score: float
    rules: list[RuleResult]


def load_signatures(signatures_file: str | None = None) -> list[dict[str, Any]]:
    if signatures_file:
        path = Path(signatures_file).expanduser().resolve()
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        payload = json.loads(
            resources.files("taco_tool.signature_data")
            .joinpath("cohesion_signatures.json")
            .read_text(encoding="utf-8")
        )

    signatures = payload.get("signatures")
    if not isinstance(signatures, list):
        raise ValueError("Invalid signatures payload: expected top-level 'signatures' list")
    return signatures


def _eval_rule(rule: dict[str, Any], metrics: dict[str, Any]) -> RuleResult:
    metric = str(rule["metric"])
    op = str(rule["operator"])
    expected = float(rule["value"])
    why = str(rule.get("why", ""))
    fix = str(rule.get("fix", ""))

    comparator = OPS.get(op)
    if comparator is None:
        raise ValueError(f"Unsupported operator '{op}' in signature rule")

    raw_actual = metrics.get(metric)
    actual = None
    passed = False

    if isinstance(raw_actual, (int, float)):
        actual = float(raw_actual)
        passed = bool(comparator(actual, expected))

    return RuleResult(
        metric=metric,
        op=op,
        expected=expected,
        actual=actual,
        passed=passed,
        why=why,
        fix=fix,
    )


def evaluate_signatures(
    metrics: dict[str, Any], signatures: list[dict[str, Any]]
) -> list[SignatureResult]:
    results: list[SignatureResult] = []

    for sig in signatures:
        rules = [_eval_rule(rule, metrics) for rule in sig.get("rules", [])]
        logic = str(sig.get("logic", "all")).lower()

        if not rules:
            matched = False
            score = 0.0
        else:
            pass_count = sum(1 for rule in rules if rule.passed)
            score = pass_count / len(rules)
            if logic == "any":
                matched = pass_count > 0
            else:
                matched = pass_count == len(rules)

        results.append(
            SignatureResult(
                signature_id=str(sig.get("id", "unknown")),
                title=str(sig.get("title", "Unnamed Signature")),
                severity=str(sig.get("severity", "medium")).lower(),
                description=str(sig.get("description", "")),
                matched=matched,
                score=score,
                rules=rules,
            )
        )

    return results


def render_text_report(
    input_markdown: Path,
    metrics: dict[str, Any],
    signature_results: list[SignatureResult],
) -> str:
    matched = [result for result in signature_results if result.matched]
    lines: list[str] = []

    lines.append(f"Document: {input_markdown}")
    lines.append(f"Signatures matched: {len(matched)}")

    if not matched:
        lines.append("Status: PASS (no suspect cohesion signatures matched)")
    else:
        lines.append("Status: SUSPECT (cohesion signatures matched)")

    key_metrics = [
        "word2vec_1_all_sent",
        "lsa_1_all_sent",
        "all_connective",
        "adjacent_overlap_binary_argument_sent",
        "adjacent_overlap_binary_noun_sent",
        "noun_ttr",
        "content_ttr",
        "repeated_content_lemmas",
        "syn_overlap_sent_noun",
    ]

    lines.append("")
    lines.append("Key metrics:")
    for metric in key_metrics:
        value = metrics.get(metric)
        if isinstance(value, float):
            lines.append(f"  - {metric}: {value:.6f}")

    if matched:
        lines.append("")
        lines.append("Detected signatures:")
        for sig in matched:
            lines.append(f"  - [{sig.severity.upper()}] {sig.title} ({sig.signature_id})")
            lines.append(f"    {sig.description}")
            for rule in sig.rules:
                actual = "missing" if rule.actual is None else f"{rule.actual:.6f}"
                mark = "match" if rule.passed else "no-match"
                lines.append(
                    f"    * {rule.metric} {rule.op} {rule.expected:.6f} | actual={actual} | {mark}"
                )
                if rule.passed and rule.why:
                    lines.append(f"      why: {rule.why}")

        fixes: list[str] = []
        for sig in matched:
            for rule in sig.rules:
                if rule.passed and rule.fix and rule.fix not in fixes:
                    fixes.append(rule.fix)

        if fixes:
            lines.append("")
            lines.append("Recommended corrections:")
            for idx, fix in enumerate(fixes, start=1):
                lines.append(f"  {idx}. {fix}")

    return "\n".join(lines)
