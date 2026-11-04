# Grading evidence: checker v2 on the six practice videos

Everything the accuracy test's numbers rest on, without the video: for each source, the reference procedure, the
planted-mistake plans, every saved model response, the grader's other inputs (self-check marks, narration, selection,
grounding) with neutral versions, the cost ledger and the claimed results.

Re-score it offline, with no key and no network:

```
.venv/bin/python -m watchverify.cli bench-replay evidence/checker-v2
.venv/bin/python -m watchverify.cli bench-replay evidence/checker-v2 --off timing    # one model-fed rule switched off
```

A match shows the published totals follow from the saved answers and the published code. It does not show the answers
are right: the step boundaries and the self-check calls come from the model under test, which is why
[docs/results.html](../docs/results.html) reports every model-fed rule with and without, and why a held-out set
(`bench/holdout.json`) was registered before download.

Footage behind these responses (openly licensed; the clips themselves are not committed): see `bench/sources.json`
for each video's title, author, license and Wikimedia Commons address.

## bolts: the same checker on two torque jobs

Kept out of the six-video totals: a 62-second stretch of "Subaru Impreza 2.5L cylinder head torque down part 6"
(CruizinMax Automotive) and a 69-second stretch of "Flaker Seal Bolt Replacement and Torque Procedures (Technical
Training)" (Hoshizaki America, Inc), both YouTube, CC BY 3.0. Re-score them the same way:
`.venv/bin/python -m watchverify.cli bench-replay evidence/bolts`. The README's Limits section says what they show.
