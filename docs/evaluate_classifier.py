"""Evaluate the production rules against the public MAST trace datasets."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from statistics import median

from agenticu.classification.classifier import Classifier
from agenticu.classification.mast_taxonomy import FAILURE_MODE_DEFINITIONS
from agenticu.models import FailureMode, Span, SpanStatus

ABSTAIN = "abstain"
REFERENCE = "95118ac951421753cf1deb87ddea3b01e693c41b"


def full_cases(path: Path) -> Iterable[tuple[str, set[str]]]:
    for row in json.loads(path.read_bytes()):
        trajectory = row["trace"]["trajectory"]
        text = (
            trajectory
            if isinstance(trajectory, str)
            else json.dumps(trajectory, ensure_ascii=False)
        )
        yield text, {mode for mode, label in row["mast_annotation"].items() if label == 1}


def human_cases(path: Path) -> Iterable[tuple[str, set[str]]]:
    for row in json.loads(path.read_bytes()):
        if row["round"] != "Generlazability":
            continue
        labels = set()
        for annotation in row["annotations"]:
            votes = [value for key, value in annotation.items() if key.startswith("annotator_")]
            if votes.count(True) > len(votes) / 2:
                labels.add(annotation["failure mode"].split(maxsplit=1)[0])
        yield row["trace"], labels


def evaluate(title: str, cases: Iterable[tuple[str, set[str]]]) -> None:
    classifier = Classifier(fast_path_only=True)
    known_modes = {mode.value for mode in FailureMode}
    expected: Counter[str] = Counter()
    predicted: Counter[str] = Counter()
    correct: Counter[str] = Counter()
    confusion: Counter[tuple[str, str]] = Counter()
    trace_sizes = []
    labeled = 0
    multi_label = 0
    matching_traces = 0
    clean_false_positives = 0
    for text, labels in cases:
        if labels - known_modes:
            raise ValueError(f"Unexpected label(s): {labels - known_modes}")
        trace_sizes.append(len(text))
        labeled += bool(labels)
        multi_label += len(labels) > 1
        expected.update(labels)
        result = classifier.classify(Span(status=SpanStatus.FAILURE), trace_text=text)
        mode = result.failure_mode.value if result.failure_mode else ABSTAIN
        predicted[mode] += 1
        if mode in labels:
            correct[mode] += 1
            matching_traces += 1
        elif not labels and mode != ABSTAIN:
            clean_false_positives += 1
        for label in sorted(labels - {mode}):
            confusion[label, mode] += 1
        if not labels and mode != ABSTAIN:
            confusion["no label", mode] += 1

    if not trace_sizes:
        raise ValueError(f"No cases were loaded for {title}")
    print(f"## {title}\n")
    print(
        f"{len(trace_sizes):,} traces, {labeled:,} with a positive label, "
        f"{multi_label:,} with multiple positive labels. Median input length was "
        f"{median(trace_sizes):,.0f} characters. The classifier matched at least one label "
        f"on {matching_traces:,} labeled traces, abstained on {predicted[ABSTAIN]:,} traces, "
        f"and assigned a mode to {clean_false_positives:,} of "
        f"{len(trace_sizes) - labeled:,} traces with no positive label.\n"
    )
    print("| Mode | Failure | Support | Predicted | Precision | Recall | F1 |")
    print("| --- | --- | ---: | ---: | ---: | ---: | ---: |")
    for mode in FailureMode:
        true_positives = correct[mode]
        precision = true_positives / predicted[mode] if predicted[mode] else 0
        recall = true_positives / expected[mode] if expected[mode] else 0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
        name = FAILURE_MODE_DEFINITIONS[mode]["name"]
        print(
            f"| {mode} | {name} | {expected[mode]} | {predicted[mode]} | "
            f"{precision:.3f} | {recall:.3f} | {f1:.3f} |"
        )

    print("\nMost common missed labels and false positives\n")
    print("| Released label | Classifier prediction | Count |")
    print("| --- | --- | ---: |")
    for (label, prediction), count in confusion.most_common(12):
        print(f"| {label} | {prediction} | {count} |")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", type=Path, required=True)
    parser.add_argument("--human", type=Path, required=True)
    args = parser.parse_args()
    print(f"Dataset revision `{REFERENCE}`.\n")
    evaluate("Full dataset with model-generated labels", full_cases(args.full))
    evaluate("Human-labeled subset using the final taxonomy", human_cases(args.human))


if __name__ == "__main__":
    main()
