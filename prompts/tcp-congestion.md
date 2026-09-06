---
id: tcp-congestion
kind: explain
intent: An open explanation request with no verdict to land. Length here is
  legitimate, so this probe guards against a rule that just compresses everything.
verdict_tokens: []
coverage: ["slow start", "congestion avoidance", "additive increase|AIMD",
  "fast retransmit|fast recovery", "CUBIC", "BBR", "duplicate ACK", "RTT",
  "window", "packet loss"]
---
Can you explain how TCP congestion control works?
