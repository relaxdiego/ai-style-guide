# no-slop-2026.09.08-minus-correctness

Diagnostic arm, not a release. `no-slop-2026.09.08` with the correctness change
reverted to its `no-slop-2026.09.07` form, and the other four kept.

The five single-change arms each landed within 7% of 09.07's coverage on
own-output-critique while the bundle lost 31%, so the damage is an
interaction rather than any one rule. Leave-one-out asks which rule's
removal brings the coverage back.

Built two ways and asserted equal: the other four edits applied forward to
09.07, and this one edit reverted out of 09.08.

No claims.yaml: these make no claims and are not scored by --check.
