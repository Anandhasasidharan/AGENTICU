# MAST classifier validation

The evaluation uses the production rule-based classifier against the authors'
released MAST traces. The full dataset has model-generated labels. The
human-labeled release contains 19 traces from annotation rounds that used
different taxonomies. Only the four traces in its final generalizability
subset use the same 14 modes as AgentICU. A human label is positive when a
majority of annotators marked it. [Dataset and annotation files](https://huggingface.co/datasets/mcemri/MAD/tree/95118ac951421753cf1deb87ddea3b01e693c41b)

Each full trajectory is classified as one text input. The released labels can
assign multiple modes to a trajectory. A prediction is correct when it matches
any positive label, and each positive label the classifier missed counts against
its mode's recall. A trace with no matching rule is an abstention. The tables use
zero when precision or recall has an empty denominator. The confusion tables count
individual missed labels and may count a trace more than once.

The live collector applies the same rules to individual error spans. This
trace-level evaluation measures agreement with the released annotations and
does not estimate detection accuracy for individual spans. Modes with F1 below
0.50 on the full dataset are marked experimental in the README. The four
human-labeled traces are too few to independently validate any mode.

## Reproduce

With AgentICU installed, download the original data and run the evaluator from
the repository root.

```bash
base=https://huggingface.co/datasets/mcemri/MAD/resolve/95118ac951421753cf1deb87ddea3b01e693c41b
curl -fLO "$base/MAD_full_dataset.json"
curl -fLO "$base/MAD_human_labelled_dataset.json"
python docs/evaluate_classifier.py --full MAD_full_dataset.json --human MAD_human_labelled_dataset.json
```

Dataset revision `95118ac951421753cf1deb87ddea3b01e693c41b`.

## Full dataset with model-generated labels

1,642 traces, 1,237 with a positive label, 1,048 with multiple positive labels. Median input length was 9,744 characters. The classifier matched at least one label on 36 labeled traces, abstained on 1,482 traces, and assigned a mode to 26 of 405 traces with no positive label.

| Mode | Failure | Support | Predicted | Precision | Recall | F1 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1.1 | Disobey Task Spec | 591 | 0 | 0.000 | 0.000 | 0.000 |
| 1.2 | Disobey Role Spec | 91 | 0 | 0.000 | 0.000 | 0.000 |
| 1.3 | Step Repetition | 664 | 43 | 0.558 | 0.036 | 0.068 |
| 1.4 | Loss of Conversation History | 117 | 0 | 0.000 | 0.000 | 0.000 |
| 1.5 | Unaware of Termination | 436 | 1 | 1.000 | 0.002 | 0.005 |
| 2.1 | Conversation Reset | 80 | 94 | 0.053 | 0.062 | 0.057 |
| 2.2 | Fail to Ask for Clarification | 265 | 0 | 0.000 | 0.000 | 0.000 |
| 2.3 | Task Derailment | 353 | 2 | 0.500 | 0.003 | 0.006 |
| 2.4 | Information Withholding | 24 | 0 | 0.000 | 0.000 | 0.000 |
| 2.5 | Ignored Other Agent Input | 370 | 1 | 1.000 | 0.003 | 0.005 |
| 2.6 | Reasoning-Action Mismatch | 610 | 2 | 0.500 | 0.002 | 0.003 |
| 3.1 | Premature Termination | 274 | 13 | 0.154 | 0.007 | 0.014 |
| 3.2 | No/Incomplete Verification | 608 | 3 | 0.333 | 0.002 | 0.003 |
| 3.3 | Incorrect Verification | 658 | 1 | 0.000 | 0.000 | 0.000 |

Most common missed labels and false positives

| Released label | Classifier prediction | Count |
| --- | --- | ---: |
| 3.3 | abstain | 584 |
| 1.3 | abstain | 577 |
| 3.2 | abstain | 536 |
| 1.1 | abstain | 534 |
| 2.6 | abstain | 533 |
| 1.5 | abstain | 379 |
| 2.5 | abstain | 322 |
| 2.3 | abstain | 302 |
| 3.1 | abstain | 233 |
| 2.2 | abstain | 223 |
| 1.4 | abstain | 95 |
| 1.2 | abstain | 82 |

Abstentions accounted for the largest missed-label counts. Conversation Reset
was the most frequent prediction. Of 94 predictions for this mode, five matched
a positive label. Step Repetition had the highest F1 at 0.068.

## Human-labeled subset using the final taxonomy

4 traces, 3 with a positive label, 3 with multiple positive labels. Median input length was 51,026 characters. The classifier matched at least one label on 0 labeled traces, abstained on 4 traces, and assigned a mode to 0 of 1 traces with no positive label.

| Mode | Failure | Support | Predicted | Precision | Recall | F1 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1.1 | Disobey Task Spec | 3 | 0 | 0.000 | 0.000 | 0.000 |
| 1.2 | Disobey Role Spec | 0 | 0 | 0.000 | 0.000 | 0.000 |
| 1.3 | Step Repetition | 0 | 0 | 0.000 | 0.000 | 0.000 |
| 1.4 | Loss of Conversation History | 0 | 0 | 0.000 | 0.000 | 0.000 |
| 1.5 | Unaware of Termination | 0 | 0 | 0.000 | 0.000 | 0.000 |
| 2.1 | Conversation Reset | 0 | 0 | 0.000 | 0.000 | 0.000 |
| 2.2 | Fail to Ask for Clarification | 0 | 0 | 0.000 | 0.000 | 0.000 |
| 2.3 | Task Derailment | 0 | 0 | 0.000 | 0.000 | 0.000 |
| 2.4 | Information Withholding | 0 | 0 | 0.000 | 0.000 | 0.000 |
| 2.5 | Ignored Other Agent Input | 0 | 0 | 0.000 | 0.000 | 0.000 |
| 2.6 | Reasoning-Action Mismatch | 0 | 0 | 0.000 | 0.000 | 0.000 |
| 3.1 | Premature Termination | 0 | 0 | 0.000 | 0.000 | 0.000 |
| 3.2 | No/Incomplete Verification | 3 | 0 | 0.000 | 0.000 | 0.000 |
| 3.3 | Incorrect Verification | 3 | 0 | 0.000 | 0.000 | 0.000 |

Most common missed labels and false positives

| Released label | Classifier prediction | Count |
| --- | --- | ---: |
| 1.1 | abstain | 3 |
| 3.2 | abstain | 3 |
| 3.3 | abstain | 3 |
