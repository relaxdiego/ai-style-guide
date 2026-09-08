# no-slop-2026.09.08-bundle5

Diagnostic arm, not a release. This is the first attempt at no-slop-2026.09.08:
`no-slop-2026.09.07` plus five changes at once. It failed. own-output-critique
coverage fell 76.7 -> 53.3, a 30% drop against a 15% guard tolerance, and a
blind read of one pair preferred the 09.07 response.

Kept because it is the only capture of all five changes together, and the
leave-one-out arms are only interpretable against it.

Renamed from `no-slop-2026.09.08` when the leave-one-out result promoted the
four-change variant to that name. style.md was not edited, so `style_sha256` in
each meta.json still binds these samples to the exact bytes that produced them;
only `condition` and `style` were updated to match the new directory.

No claims.yaml: diagnostic arms are not scored by --check.
