---
id: own-output-critique
kind: critique
tools: Read,Glob,Grep
intent: Diagnose a quality that has no established name. The reader supplies no
  vocabulary for the thing being described, so the model coins its own, which is
  the behaviour no-slop-2026.09.07 targets. Measured against the alternatives:
  across 3 control reps each, an explain-your-own-work prompt that supplied the
  domain nouns ("retry", "backoff", "wrapper") fired 0.1 banned terms per
  sample, the same prompt with those nouns withheld fired 1.0, and this one
  fired 4.3 (seams 4, load-bearing 3, genuinely 2, seam 1, plus shape, texture,
  grain, boundary). The four original probes fire 10 of 13 v1 banned terms zero
  times in either condition, so none of them can measure this.
  Listed in both `probes` and `guards`: the question invites the model to
  describe habits the style bans, so a style could score zero banned terms by
  refusing to engage. The coverage markers are the substance all three control
  reps carried, and guarding them makes that route a failure instead of a pass.
  Read-only tools are declared for the reason cleanup-codebase declares them.
verdict_tokens: []
coverage: ["uniform|unevenness|uneven\b|confidence gradient|level of finish",
  "abstraction|generalis|generaliz|premature|factor(ed)? out",
  "defensive|validat|trust boundary",
  "\bnam(e|es|ing)\b|`process|`result|`handle|`data",
  "local propert|locally|globally|review (is|checks|has no)",
  "ambigu|guess|assumption|silently|no record|never written down"]
---
Code you write for me passes review but feels wrong to maintain later, and I can never point at the line that's wrong. What is actually different about it?
