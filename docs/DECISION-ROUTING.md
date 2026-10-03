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

## Results

Pending the run.
