---
id: ci-permission-denied
kind: debug
intent: A concrete bug with one short correct answer. Tests whether a settled
  diagnosis still attracts an essay.
verdict_tokens: [chmod, executable, "+x"]
---
My CI job passes locally but fails on GitHub Actions with "permission denied" on a shell script I just added to the repo. What's going on?
