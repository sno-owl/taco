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
        raise ValueError(
            "Invalid signatures payload: expected top-level 'signatures' list"
        )
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
    include_numbers: bool = False,
) -> str:
    matched = [result for result in signature_results if result.matched]
    lines: list[str] = []

    # ── Header ────────────────────────────────────────────────────────
    if matched:
        banner = f"✗ SUSPECT  {input_markdown.name}"
        count = f"{len(matched)} signature{'s' if len(matched) != 1 else ''} matched"
    else:
        banner = f"✓ PASS     {input_markdown.name}"
        count = "no signatures matched"
    lines.append(banner)
    lines.append(count)
    lines.append("")

    if include_numbers:
        # ── Key metrics (aligned table) ───────────────────────────────
        key_metrics = [
            ("Word2Vec similarity", "word2vec_1_all_sent"),
            ("LSA similarity", "lsa_1_all_sent"),
            ("Connectives", "all_connective"),
            ("Argument overlap", "adjacent_overlap_binary_argument_sent"),
            ("Noun overlap", "adjacent_overlap_binary_noun_sent"),
            ("Noun TTR", "noun_ttr"),
            ("Content TTR", "content_ttr"),
            ("Repeated lemmas", "repeated_content_lemmas"),
            ("Synonym overlap", "syn_overlap_sent_noun"),
        ]
        label_width = max(len(label) for label, _ in key_metrics)
        for label, full in key_metrics:
            value = metrics.get(full)
            if isinstance(value, float):
                lines.append(f"  {label:<{label_width}}  {value:>7.3f}")
        lines.append("")

    # ── Matched signatures ────────────────────────────────────────────
    if matched:
        for sig in matched:
            sev = (
                "🔴"
                if sig.severity == "high"
                else "🟡"
                if sig.severity == "medium"
                else "⚪"
            )
            lines.append(f"{sev} {sig.title}")
            lines.append(f"  {sig.description}")
            lines.append("")
            if include_numbers:
                # Align rule table
                rule_label_w = max((len(r.metric) for r in sig.rules), default=0)
                for rule in sig.rules:
                    actual = "  —  " if rule.actual is None else f"{rule.actual:.3f}"
                    mark = "✓" if rule.passed else "·"
                    lines.append(
                        f"    {mark} {rule.metric:<{rule_label_w}}  {rule.op:>2} {rule.expected:.3f}  →  {actual}"
                    )
                lines.append("")

        # ── Fixes ─────────────────────────────────────────────────────
        fixes: list[str] = []
        for sig in matched:
            for rule in sig.rules:
                if rule.passed and rule.fix and rule.fix not in fixes:
                    fixes.append(rule.fix)
        if fixes:
            lines.append("Fixes:")
            for idx, fix in enumerate(fixes, start=1):
                lines.append(f"  {idx}. {fix}")

    return "\n".join(lines)
