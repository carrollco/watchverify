# watchverify: watch once, then verify

An expert does a hands-on job once, on camera. `watchverify` turns that video into a checklist a camera can
check, then checks later recordings of the same job against it, step by step, and shows you the frame where
each step happened or should have. When the camera can't see something (how tight a bolt is), it says so
instead of passing it.

Building it also produced two things that may matter as much as the checker. One is a test kit: it turns any
openly licensed how-to video into a graded exam, with code cutting steps out or swapping them so the answer key
exists before the AI sees anything, and anyone can re-score the results offline. The other is a weak spot in
Muse Spark that the test measured and that you can see frame by frame: it counts a step as done when only the
step's result is on screen.

Entry for the Meta Global AI Developer Hackathon (Cerebral Valley, online, October 26 to November 4, 2026).
Problem statement: Push the Frontier (manufacturing, repair and lab work). Track: Indie Developer. Solo entry.

- **Demo video (2:49):** built by [demo/build_video.py](demo/build_video.py) from the run page below and the
  Acer clips (video files are not in the repo), so every frame matches the code.
- **One run, start to finish:** [the Acer run page](https://carrollco.github.io/watchverify/demo-acer15.html)
  (source: [docs/demo-acer15.html](docs/demo-acer15.html)), a laptop teardown: the procedure, the tracked objects,
  the expert's own video checked, and three later performances (untouched, a step removed, two steps swapped).
- **The accuracy test:** the exam, [six videos it never saw](https://carrollco.github.io/watchverify/results-holdout.html)
  (source: [docs/results-holdout.html](docs/results-holdout.html), evidence in
  [bench/holdout-evidence/](bench/holdout-evidence/)), and the practice set,
  [six videos I built it on](https://carrollco.github.io/watchverify/results.html) (source:
  [docs/results.html](docs/results.html), evidence in [evidence/](evidence/)). Planted mistakes with the answer
  key written first; anyone can re-score both offline.

## Where it fits

What already exists, what this entry adds, and what it's good for today, as of November 2026. Sources are
linked at the end. My numbers come from small tests on short clips, so read them as rough; the last part is my
opinion.

**What's already out there.** Software that watches factory video and checks it against the written procedure
is already sold, which says the problem is real. The older kind is set up job by job: with Retrocausal you film the work, mark by hand where each step
starts and stops (about ten minutes, it says), and it trains a model for that one job; PowerArena trains a model
for each workstation's sequence and alerts when a step is skipped. Newer products use video AI, the kind of AI this
entry runs on: DeepHow sells live step checking and cites "99% task accuracy" at Foxconn without saying how that
was measured, and Invisible AI says a new line goes live in under a day with no machine-learning team (it doesn't
say whether it checks steps against a procedure). In June 2026 researchers showed that a general video AI, never
taught the specific job, spots mistakes about as well as specially trained systems on two research test sets of
cooking videos filmed from a head camera (the paper calls its method ZeProM). Testing with mistakes planted in real
videos isn't new either: PIE-V splices in generated clips instead of cutting.

**What this entry adds.** Two things:

- **Setup is one expert video.** Nobody marks steps by hand and nothing is trained for the job: Muse Spark, Meta's
  AI that understands video, writes the steps down from that one video. That's less setup than the
  film-mark-train route above, not a different league, and the newer vendors don't publish how theirs works.
- **The test is open, and its answers were fixed before the AI saw anything.** Anyone can download the exam
  videos (they're openly licensed). The answer key was saved before
  the first check; every AI answer is saved; and anyone can re-run the scoring on their own computer. False alarms
  are counted, not hidden. I couldn't find a vendor that publishes its test or its method.

**Would it prevent mistakes?** Skipped steps are the right target: in an often-quoted older study of one major
airline, 56% of 122 maintenance errors over three years were steps left out. Today it helps a person catch them; it
doesn't catch them on its own:

- It checks a recording after the fact. It prevents a defect only if someone acts on the marks before the job
  ships.
- On the exam it marked 21 of 26 cut steps as missing or worth a look, but only 8 were firm "missing" calls. The
  other 13 were "look here", and about one fine step in seven gets a "look here" too.
- Every test clip is a minute or so long. A real job can run an hour, and that is untested.
- It can't tell one bolt from another. In January 2024 a door plug blew out of Alaska Airlines flight 1282 because
  four bolts were never put back; this version would not have caught that.

This is hard for everyone. On full-length head-camera recordings with mistakes people really made, a September
2026 research system (PROVIA) catches about 15% of mistakes on one test set and 3% on another when it is allowed
one false alarm every ten minutes, and the earlier systems it beat catch less. Those numbers are measured
differently from mine, so don't line them up; they say nobody has solved this.

What it would do today: tell a supervisor which recordings to open and jump straight to the moment, instead of
watching everything or spot-checking at random. On the exam, 21 of the 26 cut steps would have been put in front
of a person as missing or worth a look, if that person can tell from the marked moment that the step is gone.

**Worth pursuing? My take:**

- **The checker: a reviewer's assistant today, not yet an inspector.** With 8 firm catches of 26, a person still
  makes the call; what it saves is the watching, by pointing at the moments worth checking.
- **The weak spot it found in Muse Spark: the most interesting result.** It counts a step as done when only the
  step's result is on screen: the cover is already off, so "take the cover off" passes, though nobody was seen
  doing it. More than half of its misses look like that, and you can watch each one frame by frame on the results
  pages. That's the wrong habit for an inspector: a part can look finished without the step having been done (a
  bolt sitting in its hole, never tightened).
- **The open exam: useful now.** A buyer can't check a vendor's "99%". This kit turns openly licensed how-to clips
  into a test with the answers fixed before the check, so any checker can be scored the same way, with false
  alarms counted. So far it only covers short clips with steps cut out by code; hour-long jobs and real human
  slips are untested.
- **Next, to make it an inspector:** name each bolt by where it is, test on hour-long recordings, and test on
  steps people really skipped instead of cut video.

Sources: Retrocausal setup ([EXTERNAL · vendor page ↗](https://retrocausal.ai/how-it-works/)); PowerArena
([EXTERNAL · vendor article ↗](https://www.powerarena.com/blog/ai-vision-sop-compliance-action-recognition-poka-yoke/));
Invisible AI, April 2026
([EXTERNAL · vendor article ↗](https://www.invisible.ai/blog/invisible-ai-launches-vision-execution-system-with-nvidia/));
DeepHow ([EXTERNAL · vendor page ↗](https://deephow.com/platform/sop-adherence)); ZeProM
([EXTERNAL · paper ↗](https://arxiv.org/abs/2606.21579)); PIE-V ([EXTERNAL · paper ↗](https://arxiv.org/abs/2604.15134));
PROVIA ([EXTERNAL · paper ↗](https://arxiv.org/abs/2609.20638)); the omissions figure
([EXTERNAL · article ↗](https://www.savvyaviation.com/human-error/)); Alaska 1282
([EXTERNAL · NTSB investigation page ↗](https://www.ntsb.gov/investigations/Pages/DCA24MA063.aspx)).

## The problem

A skipped step leaves no trace in the finished job. In January 2024 a door plug blew out of Alaska Airlines
flight 1282; its four retaining bolts had been removed during a repair and never reinstalled (NTSB report
AIR-25-04). Procedures for assembly, repair and lab work exist as documents, and a supervisor checks a sample
of the work by eye. Video of the work is cheap; nobody has time to watch it. (Fair warning: bolts are exactly
what this version can't track yet. It catches skipped steps in general, not a missing bolt; see Limits.)

## What it does

1. **Learn the job.** Muse Spark 1.3 (Meta's AI that understands video) watches the expert's video, picture and
   sound together, and fills in a fixed form: the steps in order, when each happens, the tools and parts, what
   a camera should see that proves the step was done, and what a camera can't prove (torque, a hidden latch).
2. **Follow the tools.** SAM 3.1 (Meta's AI that finds and follows objects in video) follows each tool and part
   through the video, so every step gets a measured time and a picture with the objects outlined. Muse Voice
   Transcribe writes down what the expert says, with times.
3. **Check the expert first.** The expert's own video is checked against the checklist. A step the checker
   can't see even there is marked "can't tell", so it isn't later blamed on a trainee as missing.
4. **Check a later recording.** The AI only describes what it saw and when. Plain rules in code then decide:
   pass, fail, or "a person should look" (the step wasn't seen, steps came in the wrong order, a step looks much
   shorter than the expert's, or it only turned up on a second search). A step it doesn't see gets a second,
   closer look at the stretch where it should be. If the tool is barely in use where the expert spent time, that
   can send a step to a person; it can never pass a step on its own.
5. **Report.** One web page per run: the checklist with pictures, a timeline, and for every check the frame
   where the step was seen or searched for, plus what the check cost.

## How it uses Meta's models

| Model | Used for |
|---|---|
| Muse Spark 1.3 (Responses API) | Video with its audio track in one call (`input_file`), strict JSON schema output, for extraction, checking, second looks and step boundaries |
| SAM 3.1 | Tracking the procedure's objects by noun phrase; boxes, masks and stable ids, decoded with `meta-sam-parser`; the measured step timing |
| Muse Voice Transcribe | Timed speech turns, an independent check on the narration Spark transcribes |

Every paid AI request goes through one gatekeeper ([watchverify/meta_client.py](watchverify/meta_client.py)).
It writes down what each request cost and how long it took, and refuses a request before it is sent if it would
go over the dollar limit for the run or for the whole event (Meta's billing sends an alert but has no hard cap).
The tests replay saved answers, so they never spend anything. A check of a 50-second clip costs about $0.09 at Meta's published
rates (about $0.05 for Spark, the rest for SAM's tracking); all development, every accuracy run and both bolt
videos included, cost about $62 of the event credits (ledger estimates at published rates).

## How well it works

**Short version:** it's a useful second pair of eyes, not an inspector. On six videos it had never seen, I cut
out 26 steps. It called 8 of them missing outright and sent 13 more to a person to look at; 5 slipped through.
Only the 8 are firm catches, and it also sends about one in seven perfectly fine steps to a person.

**How I tested it.** I took openly licensed videos of people doing hands-on jobs (laptop repairs, two machine
assemblies, a CRT monitor repair, cutting a bar stool out of a log). The checker learned the steps from each video. Then code made broken
copies: one step cut out, or two steps swapped. Code made the cuts, so the right answer for every copy existed
before the checker saw it.

**The real exam: six videos it never saw while I built it.** Picked at random by a recipe written down before
downloading anything, each file's digital fingerprint recorded on arrival, and graded once
([results page](https://carrollco.github.io/watchverify/results-holdout.html)).

| What I did to the video | What the checker did | Good or bad? |
|---|---|---|
| Cut out a step (26 tests) | Called it missing: 8. Sent it to a person: 13. Not caught: 5 (3 of them still had a mark on that step for another reason: "out of order" once, "done another way" twice; 2 had no mark at all) | Good: 21 of 26 noticed. It sends one fine step in seven to a person anyway (last row), so a checker that noticed nothing would still have sent about 4 of these 26; it sent 13. Bad: only 8 are firm catches |
| Swapped two steps (19 tests) | Called it out of order: 7. Sent to a person: 7 (6 with a "look here", 1 with both steps called missing instead of swapped). Slipped through: 5 | Bad: by the same one-in-seven arithmetic an untouched pair gets a "look here" about 26% of the time, and swapped pairs got one 32% of the time: a weak signal, so count on the 7 |
| Nothing (6 untouched copies) | Passed clean: 5. Sent to a person: 1 | Good |
| Steps nobody touched, inside all those copies (227) | Sent to a person: 32 (14%). Called missing or out of order: 5 (2%) | Bad: one fine step in seven gets a person's attention |

"Sent to a person" only means something because cut-out steps get sent far more often (50%) than untouched
ones (14%).

**The practice set: the six videos I built it on**
([results page](https://carrollco.github.io/watchverify/results.html)). Cut-out steps: 9 called missing, 17 sent
to a person, 15 slipped through, of 41. Swaps: 14 called out of order, 7 sent to a person, 11 slipped through,
of 32. Untouched copies: 2 of 6 passed clean. The exam came out better than practice (19% of removals slipped
through, against 37%), and with this few tests that gap could be luck. The encouraging part is the direction: a
checker tuned on its practice videos usually does worse on new ones, and this one didn't.

**Fine print, and which way each item pushes the numbers:**

- **Two backup rules do a lot of the flagging** (makes it look better than it is). One watches how long the tool
  is in use at each step; the other flags a step much shorter than the expert's. With both off, 13 of the 26
  exam removals slip through instead of 5. They're part of the checker, so they count, but they also cause most
  of the false alarms.
- **The answer key got a light check** (could go either way). A different AI model (not the one being tested)
  proposed where each step starts and ends
  from still frames. I spent about two minutes on the first video and 3 to 8 seconds on each of the other five,
  and changed nothing. The AI being tested never touched the answer key.
- **Some tests were left out** (makes it look better). The answer key marked a few steps "a camera can't see
  this", so tests on them weren't graded. Graded anyway, both of those removals slipped through (5 of 28 instead
  of 3 of 26), and missed swaps go from 5 of 19 to 7 of 23.
- **The checker writes its own list of steps** (makes it look better). Every number is "of the steps it listed"; a step
  it never listed can't be tested here. On one laptop it even wrote a step backwards ("press the RAM in" where
  the video shows it coming out); I left that in, and both tests on that step went its way.
- **Some cuts take out a lot** (about neutral). Cutting a step also removes the in-between footage on both sides
  of it, and on 7 of the 26 exam removals that was over 30% of the clip. Those weren't easier: 3 called missing,
  1 sent to a person, 3 slipped through.
- **One way the test is harder than real life** (makes it look worse). When code cuts out "take the cover off", the
  cover is still off in the next shot. Both exam removals that got no mark at all went exactly like
  that ("video starts with bottom cover already off"). In a real skipped step the cover would still be on.
- **On the practice set the AI drew its own cut lines** (makes it look better), so some removals it couldn't
  separate were left out. Grade those too and 23 of 55 removals are missed instead of 12 of 41.
- **The untouched copies are the expert's own video** (makes it look better). Re-cut the same way as the broken
  copies, but the same hands, camera and light as the checklist it was written from, so passing clean is easier
  than it would be for a different person doing the job.
- **Small numbers.** 26 removal tests on the exam. Read every percentage here as rough.

**What I tried that didn't help.** Two changes to the checker, tested on the practice set: asking it to say
whether it saw each step being done or only its result, and letting it think harder. Neither beat the original
on the tests I wrote down before running them, so the original took the exam.

**What holds up regardless of the score:**

- **No peeking.** The checker never sees file names or the answer key. A test plants fake answer-key values
  everywhere and fails if any reach the model ([tests/test_leaks.py](tests/test_leaks.py),
  [tests/test_leaks_labels.py](tests/test_leaks_labels.py)); I checked it by planting a leak and watching it fail.
- **Anyone can re-score it.** Every AI answer is saved, and `bench-replay` re-scores every row with no key and
  no internet: 64 of 64 rows on the exam, 120 of 120 on practice.
- **Checked before I saw it.** Before any exam number reached me, a separate AI reviewer traced everything the
  grader could see and confirmed the answer key was saved before the first check.

**What I'd use it for today:** pointing a supervisor at the recordings worth watching and jumping straight to
the frame. Not signing off a job by itself.

## Run it

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export MODEL_API_KEY=...            # a Meta Model API key; never committed
.venv/bin/python -m watchverify.cli --run demo --budget 0.50 extract expert.mp4 --name reference
.venv/bin/python -m watchverify.cli --run demo --budget 0.50 ground runs/demo/reference.procedure.json expert.mp4
.venv/bin/python -m watchverify.cli --run demo --budget 0.50 self-check runs/demo/reference.procedure.json expert.mp4
.venv/bin/python -m watchverify.cli --run demo --budget 0.50 verify runs/demo/reference.procedure.json trainee.mp4
.venv/bin/python -m watchverify.cli --run demo report          # runs/demo/report.html
.venv/bin/python -m watchverify.cli --run demo ledger
```

`--budget` is the run's dollar ceiling. `cut` builds test variants from a clip
(`cut src.mp4 out.mp4 0:12 15.5:20`).

Re-score the accuracy test offline, no key needed:

```
.venv/bin/python -m watchverify.cli bench-replay evidence/checker-v2
.venv/bin/python -m watchverify.cli bench-replay evidence/checker-v2 --off timing
.venv/bin/python -m watchverify.cli bench-replay bench/holdout-evidence            # the exam
```

Tests replay saved responses and never call a paid model: `.venv/bin/python -m pytest tests`.

The accuracy test itself (`bench-prepare`, `bench-boundaries`, `bench-run`, `bench-score`, `bench-report`) and
the held-out guard (`holdout-register`, the `labels` cut method, the label confirm page) are in
[watchverify/bench.py](watchverify/bench.py) and [watchverify/labels.py](watchverify/labels.py);
`python -m watchverify.cli --help` lists every command.

## Repository

| Path | What |
|---|---|
| `watchverify/` | The package: client, ledger and budget, schema, extract, ground, verify, timing, report, bench, labels, CLI |
| `tests/` | Replay tests, leak canaries, budget, rules, timing, labels, report |
| `docs/` | The demo run page and the accuracy results page |
| `evidence/` | Grading evidence (no video): `checker-v2/` for the six practice videos, `bolts/` for the two torque jobs |
| `bench/` | The practice sources; the held-out set's registry, answer key (`holdout-labels/`) and grading evidence (`holdout-evidence/`) |
| `demo/` | The script that builds the demo video |

## What is new, and what is not

All code in this repository was written during the event (October 27 to November 4, 2026). Pre-existing
work used as dependencies, declared in `requirements.txt` and `demo/requirements.txt`: the OpenAI Python SDK
(Meta's API is compatible with it), `meta-sam-parser` (Meta's parser for SAM output), `imageio-ffmpeg` (a
bundled ffmpeg), `httpx`, `pytest`, and for the demo video only, Playwright (renders the pages) and
kokoro-onnx with the Kokoro-82M voice model (the narration; Apache 2.0). No code was copied from
any other project.

## Footage

All openly licensed, from Wikimedia Commons; the clips are not committed. Each was shortened to a 30 to 75
second stretch and cut into versions with a step removed or two steps swapped.

| Id | Video | Author | License |
|---|---|---|---|
| acer15 | [How to open Acer Aspire 15 (A15-41M) - disassembly and upgrade options](https://commons.wikimedia.org/wiki/File:How_to_open_Acer_Aspire_15_(A15-41M)_-_disassembly_and_upgrade_options.webm) | LaptopMedia | CC BY 3.0 |
| asusp16 | [How to open ASUS ProArt P16 (H7606) - disassembly and upgrade options](https://commons.wikimedia.org/wiki/File:How_to_open_ASUS_ProArt_P16_(H7606)_-_disassembly_and_upgrade_options.webm) | LaptopMedia | CC BY 3.0 |
| dell3550 | [How to open Dell Latitude 3550 - disassembly and upgrade options](https://commons.wikimedia.org/wiki/File:How_to_open_Dell_Latitude_3550_-_disassembly_and_upgrade_options.webm) | LaptopMedia | CC BY 3.0 |
| hp440 | [How to open HP ProBook 440 G11 - disassembly and upgrade options](https://commons.wikimedia.org/wiki/File:How_to_open_HP_ProBook_440_G11_-_disassembly_and_upgrade_options.webm) | LaptopMedia | CC BY 3.0 |
| powercube | [Powercube v7 Assembly](https://commons.wikimedia.org/wiki/File:Powercube_v7_Assembly.ogv) | Open Source Ecology | CC BY-SA 3.0 |
| brickpress | [Liberator Compressed Earth Brick Press v4 Assembly](https://commons.wikimedia.org/wiki/File:Liberator_Compressed_Earth_Brick_Press_v4_Assembly.ogv) | Open Source Ecology | CC BY-SA 3.0 |

The torque jobs in Limits, both on YouTube under CC BY 3.0: "Subaru Impreza 2.5L cylinder head torque down part 6"
by CruizinMax Automotive (https://www.youtube.com/watch?v=WJKaM7ZqtIY), a 62-second stretch of the tightening;
and "Flaker Seal Bolt Replacement and Torque Procedures (Technical Training)" by Hoshizaki America, Inc
(https://www.youtube.com/watch?v=lWxNOm2Yf1s), a 69-second stretch of the housing bolts.

The exam's six videos (the held-out set), also from Wikimedia Commons:

| Id | Video | Author | License |
|---|---|---|---|
| nitrov15 | [2026-08-13 How to open Acer Nitro V 15 (ANV15-A31) - disassembly and upgrade options](https://commons.wikimedia.org/wiki/File:2026-08-13_How_to_open_Acer_Nitro_V_15_(ANV15-A31)_-_disassembly_and_upgrade_options.webm) | LaptopMedia | CC BY 4.0 |
| thinkpadt14 | [How to open Lenovo ThinkPad T14 Gen 5 (Intel) - disassembly and upgrade options](https://commons.wikimedia.org/wiki/File:How_to_open_Lenovo_ThinkPad_T14_Gen_5_(Intel)_-_disassembly_and_upgrade_options.webm) | LaptopMedia | CC BY 3.0 |
| thinkbook13x | [How to open Lenovo Thinkbook 13x Gen 4 - disassembly and upgrade options](https://commons.wikimedia.org/wiki/File:How_to_open_Lenovo_Thinkbook_13x_Gen_4_-_disassembly_and_upgrade_options.webm) | LaptopMedia | CC BY 3.0 |
| msicyborg14 | [How to open MSI Cyborg 14 A13V - disassembly and upgrade options](https://commons.wikimedia.org/wiki/File:How_to_open_MSI_Cyborg_14_A13V_-_disassembly_and_upgrade_options.webm) | LaptopMedia | CC BY 3.0 |
| sonypvm | [Sony PVM 8041Q - Black & White to Color CRT Repair - Retro Tech](https://commons.wikimedia.org/wiki/File:Sony_PVM_8041Q_-_Black_%26_White_to_Color_CRT_Repair_-_Retro_Tech.webm) | Retro Tech | CC BY 3.0 |
| logstool | [Video of making of log furniture cutting a bar stool from a log](https://commons.wikimedia.org/wiki/File:Video_of_making_of_log_furniture_cutting_a_bar_stool_from_a_log.webm) | Sillerkiil | CC BY-SA 4.0 |

## Limits

- A camera sees what happened, not how hard: torque, a seated connector or a hidden clip are reported as
  "cannot see", never as passed.
- Tested on laptop teardowns and machine assemblies from fixed cameras; not yet on a phone in a real shop.
- **It cannot yet tell one bolt from another.** Tried on two openly licensed torque jobs: a cylinder-head
  torque-down (fixed camera) and Hoshizaki's own technical-training video on gear-motor housing bolts torqued in a
  cross pattern. The procedures describe most steps alike ("seat torque wrench onto next bolt"), and the checker
  matches every step to whatever wrench visits remain: of 13 removed bolts it caught none (5 sent to a person, at
  about the untouched-step rate, so no signal; 8 missed), of 11 swapped pairs none, and one of the two untouched
  copies went to review. A torque sequence needs each bolt named by its place (the service manual's numbering)
  and the visits counted; that is the next mechanism, not a prompt tweak. Evidence: [evidence/bolts/](evidence/bolts/).
- Too many untouched steps go to a person (one in seven), and a step's result on screen too often counts as the
  step being done. Those are the next two things to fix; the held-out set is spent, so a fix needs a fresh one.
