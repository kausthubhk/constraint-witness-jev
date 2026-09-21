# Data audit

The committed heldout V1 fixtures are retained byte-for-byte. Known quality
limitations are documented here rather than repaired in place.

## Heldout V1

`heldout-11-recovery` contains a recovery field whose event does not
independently establish restoration of the original bytes. It remains useful
for compatibility and validation coverage, but must not contribute to a
recovery metric unless an independent evidence check confirms restoration.

The heldout cohort also has limited trajectory depth and several cases whose
outcomes are `unknown`, `ungradeable`, or `ambiguous`. It is historical pilot
data, not a source for tuning thresholds or making a semantic performance
claim.

## Semantic development V1

`fixtures/semantic-development-v1` contains six synthetic, multi-event cases
with independent human annotation as the next step. They intentionally have
no finalized labels. The source hashes bind each case's ordered observable
evidence recipe and the manifest binds the ordered case hash list.

The cases cover protected reads and writes, intent without effect, an
unverified recovery claim, shell redirection, and an API compatibility case.
The cohort is annotation-ready; it is not an evaluated or heldout result.
