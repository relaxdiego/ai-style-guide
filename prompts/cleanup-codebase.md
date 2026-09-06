---
id: cleanup-codebase
kind: underspecified
tools: Read,Glob,Grep
intent: Too vague to answer without more information. Asking a clarifying
  question is the correct move, and a rule that suppresses questions wholesale
  will show up here. Needs read-only tools despite having nothing to read: with
  no tools at all the model emits hallucinated tool-call markup instead of
  prose, in 5 of 10 samples. Given tools and an empty sandbox it looks, finds
  nothing, and asks. Both conditions see the same empty sandbox.
verdict_tokens: []
coverage: ["log|output|error", "repo|path|project|directory",
  "GitHub Actions|Vercel|Fly|k8s|target|platform|pipeline"]
---
My deploy started failing yesterday and I don't know why. Can you help?
