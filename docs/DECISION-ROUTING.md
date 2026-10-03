# Decision routing with an abstain outcome

The decision router picks a lane for a request as a typed choice over the roster, with a probability for each lane. When the top lane's probability is under a calibrated threshold, it returns ABSTAIN, and the request goes to a person or a larger model in place of a guessed lane. The lexical router stays the default; the decision router is opt-in.

## Bar, set before the run

This bar was committed before the router was written and before its author saw the labelled set.

**Labels.** 140 requests written by a separate labeller who saw only lane names and descriptions, never keywords or code, each with one gold lane (`tests/fixtures/forum_routing_labels.json`). The planned label source, the routing-accuracy records in the local metrics store, holds 2 records, too few to measure anything, so it was replaced.

**Split.** Items are split in half by a seeded hash of their id. The threshold is chosen on the dev half only: the lowest threshold whose dev abstain rate is at least 10%. All bar numbers come from the test half.

- **A1, accuracy.** The decision router's top-1 accuracy is at least the lexical router's top-1 accuracy (its first candidate, counted on every item).
- **A2, abstain rate.** Under 15% of test items abstain.
- **A3, abstain carries error.** The top-1 error rate on abstained items is at least twice the error rate on decided items.
- **Control.** With the gold labels shuffled, A3 must fail. If shuffled labels also give a ratio of 2 or more, the ratio measures nothing.
- **Ship rule.** The router ships opt-in whatever the result, with the numbers below.

## Try it

```bash
forum route --router decision "write a CUDA kernel for matrix multiply"
forum route --router decision --threshold 0.5 "react to the database change"
python -m forum.decision_routing_bench tests/fixtures/forum_routing_labels.json
```

Each lane is scored with BM25 against a short lane document (keywords counted twice, the domain description and the lane name), and a softmax turns scores into probabilities. With the default threshold of 0.0 the router abstains only when no lane matches any word of the request. A higher `--threshold` also abstains on weak matches.

## Results

Run on 2026-10-03, seed 20261003. Dev half 66 items, test half 74. The calibration rule picked a threshold of 0.0: more than 10% of dev requests matched no lane at all, so abstaining on those alone met the 10% floor.

| Test half, 74 items | Decision router | Lexical router |
|---|---|---|
| Top-1 accuracy | 0.58 (43 of 74), Wilson 0.47 to 0.69 | 0.46 (34 of 74), Wilson 0.35 to 0.57 |
| Abstain or escalate rate | 0.19 (14 of 74) | 0.99 (73 of 74) |
| Error rate when decided | 0.28 | 0.00 (1 item) |
| Error rate when abstained | 1.00 | 0.55 |

- **A1 passes.** Top-1 accuracy rose from 0.46 to 0.58. The Wilson intervals overlap, so the gain is suggestive at this sample size.
- **A2 fails.** 19% of test requests abstain, above the 15% bar. Every abstain is a request that shares no word with any lane document. A threshold cannot lower that rate; a semantic channel, or richer lane documents, would be needed.
- **A3 passes, with a caveat.** Abstained items err at 1.00 against 0.28 for decided items, a ratio of 3.5. At threshold 0.0 an abstained request matched no lane, so its top-1 lane is the alphabetical first and the high error is close to built in. At threshold 0.5, where weak matches also abstain, the ratio is 2.1.
- **The control fails A3 as required.** With shuffled labels the ratio is 1.01.

The lexical router escalated 73 of 74 requests written in plain language. Its keyword rules need several exact hits before deciding, so in practice it routes almost nothing without a person. The decision router decides 81% of the same requests at 72% accuracy on the decided ones.

Threshold sensitivity on the test half, reported after the run and not used to pick anything: 0.5 abstains on 39% (ratio 2.1), 0.8 on 72% (decided error 0.10).

## Limits

The labels come from one labeller, a Claude subagent that saw only lane names and descriptions. They are independent of the router's code and keywords but are not a person's routing records. 74 test items give wide intervals. The lane documents are the default roster's; a custom roster with sparse descriptions will abstain more.
