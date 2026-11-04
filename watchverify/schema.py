"""The two schemas the whole pipeline is driven by: a Procedure (from one video) and a Verification
(one procedure checked against another). Strict-subset JSON Schema (root object, additionalProperties
false, all properties required), which is what Meta's structured output validates."""

STEP = {"type": "object", "additionalProperties": False, "properties": {
    "index": {"type": "integer"},
    "start_s": {"type": "number"}, "end_s": {"type": "number"},
    "action": {"type": "string", "description": "one verb phrase, what the hands do"},
    "objects": {"type": "array", "items": {"type": "string"},
                "description": "parts and tools involved, as concrete noun phrases a segmentation model can track"},
    "observable_checkpoint": {"type": "string", "description": "what a camera can see that shows the step was done"},
    "pass_condition": {"type": "string"},
    "cannot_see": {"type": "string", "description": "a property of this step the camera cannot verify, or 'none'"},
    "checkpoint_visibility": {"type": "string", "enum": ["clear", "subtle", "narration_only"],
                              "description": "clear: the checkpoint is plainly visible in the frames; subtle: visible only "
                                             "briefly, partly, small or occluded; narration_only: known from the speech, not visible"},
    "evidence_s": {"type": "number", "description": "the second in this video where the checkpoint is best seen"}},
    "required": ["index", "start_s", "end_s", "action", "objects", "observable_checkpoint", "pass_condition", "cannot_see",
                 "checkpoint_visibility", "evidence_s"]}

PROCEDURE = {"type": "object", "additionalProperties": False, "properties": {
    "task": {"type": "string"},
    "steps": {"type": "array", "items": STEP},
    "objects_seen": {"type": "array", "items": {"type": "string"}},
    "speech_heard": {"type": "string", "description": "transcript of any speech in the audio track, or 'none'"},
    "audio_notes": {"type": "string", "description": "non-speech sounds that carry information, or 'none'"},
    "uncertainty": {"type": "string"},
    "track": {"type": "array", "items": {"type": "string"},
              "description": "up to four noun phrases, copied exactly from the steps' objects, whose position in the frame "
                             "shows the task progressing: the tools first, then the parts that move; never hands or gloves, "
                             "not the whole workpiece, not the background"}},
    "required": ["task", "steps", "objects_seen", "speech_heard", "audio_notes", "uncertainty", "track"]}

EXTRACT_INSTRUCTIONS = (
    "You turn a video of a hands-on task into a step procedure with evidence. Every step names what the "
    "camera can see that proves it was done, and names what the camera cannot verify. Use the video's "
    "timeline in seconds. Be concrete: nouns a segmentation model could track. Rate each checkpoint's visibility "
    "honestly: a checkpoint you know only from the narration is narration_only, even if the step surely happened. "
    "One step per place or part: when the hands move to a different edge, side, corner or part, start a new step, "
    "even if the action repeats, so that skipping any one place shows as a missing step. Only steps the hands "
    "perform on the task: leave out title cards, screenshots, on-screen text, graphics or animations drawn over "
    "the video, close-ups that only show a label, and pointing at parts.")
EXTRACT_PROMPT = "Watch this clip and produce the step procedure. Also transcribe any speech you hear."


MOMENT = {"type": "object", "additionalProperties": False, "properties": {
    "start_s": {"type": "number"}, "end_s": {"type": "number"}}, "required": ["start_s", "end_s"]}

STEP_CHECK = {"type": "object", "additionalProperties": False, "properties": {
    "reference_step": {"type": "integer"},
    "status": {"type": "string", "enum": ["observed", "done_differently", "not_observed", "unclear"],
               "description": "observed: the step's observable checkpoint is visible in the video; done_differently: the "
                              "step's result is visible but reached another way than the reference says (another tool, "
                              "by hand); not_observed: the video was watched and the checkpoint never appears; unclear: cannot tell"},
    "observed_start_s": {"type": "number", "description": "seconds in the candidate video where the step starts, -1 if not observed"},
    "observed_end_s": {"type": "number", "description": "-1 if not observed"},
    "other_moments": {"type": "array", "items": MOMENT,
                      "description": "other stretches where this step's checkpoint may also be what is seen (a similar "
                                     "action at another time), besides observed_start_s to observed_end_s; empty if none"},
    "evidence": {"type": "string", "description": "what is visible that supports the status, with seconds"},
    "cannot_see": {"type": "string", "description": "properties of this step the camera cannot verify, or 'none'"}},
    "required": ["reference_step", "status", "observed_start_s", "observed_end_s", "other_moments", "evidence", "cannot_see"]}

EXTRA_ACTION = {"type": "object", "additionalProperties": False, "properties": {
    "start_s": {"type": "number"}, "end_s": {"type": "number"}, "action": {"type": "string"}},
    "required": ["start_s", "end_s", "action"]}

VIDEO_VERIFICATION = {"type": "object", "additionalProperties": False, "properties": {
    "same_task": {"type": "boolean"},
    "checks": {"type": "array", "items": STEP_CHECK},
    "extra_actions": {"type": "array", "items": EXTRA_ACTION},
    "notes": {"type": "string"}},
    "required": ["same_task", "checks", "extra_actions", "notes"]}

VERIFY_VIDEO_INSTRUCTIONS = (
    "You are given a reference procedure (an expert's steps, each with an observable checkpoint) and a video "
    "of another performance of the task. For every reference step, decide from the video alone whether its "
    "observable checkpoint is visible, and at what seconds. Judge only what is visible; properties that cannot "
    "be seen go in cannot_see, never into the status. Do not infer a step from neighboring steps or from the "
    "reference's timing: the performer may skip or reorder steps. List actions in the video that are not in "
    "the reference. Report every reference step exactly once, in reference order. When reference frames are "
    "given, they show what each step looks like in the expert's video; compare like with like. Use unclear "
    "when a subtle checkpoint might be present but you cannot tell. Judge a step by its result, what is "
    "different afterwards: when the result is visible but reached another way than the reference describes "
    "(another tool, by hand), use done_differently and say how in evidence. A similar action can happen more "
    "than once: give the clearest moment as observed_start_s to observed_end_s and list any other moment that "
    "could be this step in other_moments.")

SECOND_LOOK = {"type": "object", "additionalProperties": False, "properties": {
    "status": {"type": "string", "enum": ["observed", "done_differently", "not_observed", "unclear"]},
    "observed_start_s": {"type": "number", "description": "seconds in this clip where the step starts, -1 if not observed"},
    "observed_end_s": {"type": "number", "description": "-1 if not observed"},
    "evidence": {"type": "string", "description": "what is visible that supports the status, with seconds in this clip"}},
    "required": ["status", "observed_start_s", "observed_end_s", "evidence"]}

SECOND_LOOK_INSTRUCTIONS = (
    "You are given one step of a hands-on procedure, a frame showing that step in an expert's video, and a short "
    "clip from another performance. Decide from the clip alone whether this step's observable checkpoint is "
    "visible in it. observed: you can point to the seconds where it happens. done_differently: its result is "
    "visible but reached another way (another tool, by hand); say how. not_observed: you watched the whole "
    "clip and it does not happen. unclear: it might be happening but the view does not let you tell. The clip may "
    "well not contain the step; do not assume it does.")

# Checker v3, the act rule (2026-11-03 night). Reading the frames at the seconds v2 claimed: in all 12 missed removals
# the model reported the removed step seen, and about 7 of the 12 claims were the step's result only (the cover already
# off, the frame already standing). v2's instructions said "Judge a step by its result", so a result-only sighting
# passed. v3 asks whether the step was seen being done; code sends a result-only sighting to review (use_act).
SEEN_AS = {"type": "string", "enum": ["act", "result_only", "not_seen"],
           "description": "act: within the seconds given, the hands or tool are seen doing this step, making its change; "
                          "result_only: only the state after the step is seen (it was done before the video starts, off "
                          "camera, or between two shots); not_seen: neither"}
STEP_CHECK_ACT = dict(STEP_CHECK, properties=dict(STEP_CHECK["properties"], seen_as=SEEN_AS),
                      required=STEP_CHECK["required"] + ["seen_as"])
VIDEO_VERIFICATION_ACT = dict(VIDEO_VERIFICATION, properties=dict(VIDEO_VERIFICATION["properties"],
                                                                  checks={"type": "array", "items": STEP_CHECK_ACT}))
SECOND_LOOK_ACT = dict(SECOND_LOOK, properties=dict(SECOND_LOOK["properties"], seen_as=SEEN_AS),
                       required=SECOND_LOOK["required"] + ["seen_as"])
_ACT_SENTENCE = (" A step counts as observed only when you see it being done: the hands or tool making its change. "
                 "When you see only the state after it (the step already looks done, but the doing is not shown: it "
                 "happened before the video starts, off camera, or between two shots), report seen_as result_only. "
                 "Do not credit a step with an action that belongs to another step, even a similar one at another "
                 "place.")
VERIFY_VIDEO_INSTRUCTIONS_ACT = VERIFY_VIDEO_INSTRUCTIONS.replace(
    "Judge a step by its result, what is different afterwards: when the result is visible but reached another way "
    "than the reference describes (another tool, by hand), use done_differently and say how in evidence.",
    "When the step is seen being done but another way than the reference describes (another tool, by hand), use "
    "done_differently and say how in evidence.") + _ACT_SENTENCE
SECOND_LOOK_INSTRUCTIONS_ACT = SECOND_LOOK_INSTRUCTIONS + _ACT_SENTENCE


BOUNDARY = {"type": "object", "additionalProperties": False, "properties": {
    "first_ends_s": {"type": "number", "description": "time label of the last frame where the hands still do step A; -1 if no frame shows it"},
    "second_begins_s": {"type": "number", "description": "time label of the first frame where the hands begin step B; -1 if no frame shows it"},
    "evidence": {"type": "string", "description": "what the hands do in the frames around both times"}},
    "required": ["first_ends_s", "second_begins_s", "evidence"]}

BOUNDARY_INSTRUCTIONS = (
    "You are given two consecutive steps of a hands-on procedure and a strip of frames from the expert's video, "
    "in time order, each labeled with its time in seconds. Find where step A's hand work ends and step B's begins. "
    "first_ends_s: the label of the last frame in which the hands are still doing step A (holding the tool at "
    "step A's place or part, or finishing its action). second_begins_s: the label of the first frame in which "
    "the hands are at step B's place or part, or start its action. Moving between places, putting a tool down or "
    "picking one up belongs to neither step. Be strict: a frame that might still be step A counts as step A. "
    "Answer only from the frames; use -1 when no frame shows the step.")


SHORTENED_RATIO = 0.4   # a step seen for under 40% of the expert's time is flagged for review


SOFTENINGS = ("marks", "narration", "timing", "moments", "confirm", "span", "act")
# Rules off unless named with a "+" in a switch list. The SAM order rule failed the identical-footage test (audit of
# 2026-11-03): on an untouched re-encoded copy of the expert's clip it saw steps begun in the opposite order, because a
# 0.6 s run at a step's place counts as "begun", so its flags are noise; it is reported only as a with-it row.
OPT_IN = ("+sam_order",)


def rules_for(off: tuple[str, ...] = ()) -> dict[str, bool]:
    """apply_order_rules' switches from a switch list: SOFTENINGS on unless named, OPT_IN off unless named."""
    rules = {f"use_{k}": k not in off for k in SOFTENINGS}
    rules["use_sam_order"] = "+sam_order" in off
    return rules
REASONS = {     # code on a check (c["reasons"]): what a person reading the page is told
    "model_unclear": "the checker said it cannot tell", "done_differently": "result reached another way",
    "narration_only": "checkpoint only heard, never seen", "self_check_mark": "not found in the expert's own clip",
    "sam_saw_tool": "missing to the checker, but SAM tracked the tool there", "sam_never_tracked": "seen, but SAM never tracked the tool there",
    "sam_shortened": "SAM measured under 40% of the expert's time", "model_seconds_shortened": "seen for under 40% of the expert's time",
    "second_look_only": "seen only on the second look", "sam_order": "SAM saw a later step's place first",
    "other_moment": "out of order, unless at another moment the checker listed",
    "confirm_not_seen": "not seen on a second look at the stretch where the check placed it",
    "result_only": "only its result was seen, not the step being done"}
PRESENT = ("observed", "done_differently")      # statuses that place a step in the video, for order
MAX_OTHER_MOMENTS = 3


def order_moments(present: list[dict]) -> dict[int, float]:
    """For each present step, the start of one of its moments: the model's clearest, or one it listed in
    other_moments, chosen so that as few pairs as possible run against the reference order; ties keep the clearest.
    A listed moment that overlaps another present step's own moment is not admissible (it is that step's moment).
    present is in reference order. apply_order_rules uses this only to send a pair to review, never to clear it."""
    import itertools
    own = [(c["observed_start_s"], c["observed_end_s"]) for c in present]
    def admissible(i, m):
        return m["start_s"] >= 0 and not any(j != i and m["start_s"] < b and a < m["end_s"] for j, (a, b) in enumerate(own))
    cands = [[(c["observed_start_s"], 0)] + [(m["start_s"], 1) for m in (c.get("other_moments") or [])[:MAX_OTHER_MOMENTS]
                                             if admissible(i, m)] for i, c in enumerate(present)]
    best = None
    for combo in itertools.product(*cands):
        inv = sum(1 for i in range(len(combo)) for j in range(i + 1, len(combo)) if combo[j][0] < combo[i][0])
        key = (inv, sum(x[1] for x in combo))
        if best is None or key < best[0]:
            best = (key, combo)
    return {c["reference_step"]: t for c, (t, _) in zip(present, best[1] if best else [])}


def apply_order_rules(reference: dict, v: dict, use_timing: bool = True, use_marks: bool = True,
                      use_narration: bool = True, use_moments: bool = True, use_confirm: bool = True,
                      use_span: bool = True, use_sam_order: bool = False, use_act: bool = True) -> dict:
    """Code, not the model, decides order violations and the verdict from the reported observations. Rules
    start from each check's seen_status (what the model, and a second look, reported), so they can be
    re-applied to saved observations for free when the reference changes (rescore).
    Three rules rest on model outputs other than the check itself (SOFTENINGS), and each can be switched off so a
    score is reported with and without it: the self-check marks (use_marks) and the narration-only visibility
    (use_narration) turn a missing step into "can't tell"; SAM's measured seconds (use_timing) do that or send a
    step to review."""
    checks = sorted(v["checks"], key=lambda c: c["reference_step"])
    steps = {st["index"]: st for st in reference.get("steps", [])}
    for c in checks:
        c["status"] = c.setdefault("seen_status", c["status"])
        c["out_of_order"] = False; c["shortened"] = False; c.pop("status_reason", None)
        c["reasons"] = ["model_unclear"] if c["status"] == "unclear" else ["done_differently"] if c["status"] == "done_differently" else []
        # the two looks disagree: the first pass did not see the step, the second look did; a person decides
        c["disputed"] = c["status"] == "observed" and (c.get("second_look") or {}).get("first_pass", {}).get("status") == "not_observed"
        st = steps.get(c["reference_step"], {})
        if c["status"] == "not_observed":
            # a checkpoint the camera cannot show cannot be found missing by a camera
            if use_narration and st.get("checkpoint_visibility") == "narration_only":
                c["status"] = "unclear"; c["reasons"].append("narration_only")
                c["status_reason"] = "the reference checkpoint is only in the narration; the camera cannot confirm or rule it out"
            elif use_marks and st.get("self_check", "observed") != "observed":
                c["status"] = "unclear"; c["reasons"].append("self_check_mark")
                c["status_reason"] = "this checkpoint was not visible even in the expert's own video, so the camera cannot rule it out"
        m = c.get("measured") if use_timing else None
        if m and m.get("measurable"):
            # a second sensor: SAM measured the tool's time at this step's place; agree, decide; disagree, review
            ref_s, seen_s = m["ref_seconds"], m["seconds"]
            if c["status"] == "not_observed" and seen_s >= SHORTENED_RATIO * ref_s:
                c["status"] = "unclear"; c["reasons"].append("sam_saw_tool")
                c["status_reason"] = (f"the model did not see it, but the tool was tracked at this step's place for "
                                      f"{seen_s:.1f} s (expert: {ref_s:.1f} s)")
            elif c["status"] == "observed" and seen_s == 0:
                c["disputed"] = True; c["reasons"].append("sam_never_tracked")
                c["status_reason"] = "the model saw it, but the tool was never tracked at this step's place"
            elif c["status"] == "observed" and seen_s < SHORTENED_RATIO * ref_s:
                c["shortened"] = True; c["reasons"].append("sam_shortened")
                c["status_reason"] = f"measured {seen_s:.1f} s at this step's place; the expert took {ref_s:.1f} s"
        if use_span and c["status"] == "observed" and "end_s" in st and not c["shortened"]:
            # the model's own seen span, whether or not SAM measured: a second sensor may add a flag, never clear one
            ref_len = st["end_s"] - st["start_s"]; seen_len = c["observed_end_s"] - c["observed_start_s"]
            if ref_len >= 2.0 and seen_len < SHORTENED_RATIO * ref_len:
                c["shortened"] = True; c["reasons"].append("model_seconds_shortened")
                c["status_reason"] = f"seen for {seen_len:.1f} s; the expert took {ref_len:.1f} s"
        cl = c.get("confirm_look")
        if use_confirm and cl and c["status"] in PRESENT and cl["status"] == "not_observed":
            # the two looks disagree: the check placed the step there, a look at that stretch alone did not see it
            c["disputed"] = True; c["reasons"].append("confirm_not_seen")
            c["status_reason"] = (c.get("status_reason", "") + "; " if c.get("status_reason") else "") + \
                "a second look at the stretch where the check placed it did not see it"
        seen_as = [x for x in (c.get("seen_as"), (cl or {}).get("seen_as")) if x]
        if use_act and c["status"] in PRESENT and any(x != "act" for x in seen_as):
            # checker v3: a step placed in the video must be seen being done; its result alone may be work done off
            # camera, or (in the accuracy test) a removed step whose result still shows after the cut. Checks without
            # seen_as (v2) are untouched.
            c["disputed"] = True; c["reasons"].append("result_only")
            c["status_reason"] = (c.get("status_reason", "") + "; " if c.get("status_reason") else "") + \
                "only the step's result was seen, not the step being done"
        if c["disputed"] and (c.get("second_look") or {}).get("first_pass", {}).get("status") == "not_observed":
            c["reasons"].append("second_look_only")
            c["status_reason"] = (c.get("status_reason", "") + "; " if c.get("status_reason") else "") + \
                "seen only on the second look; the first pass did not see it"
    if use_timing and use_sam_order:
        # measured order: a later step's place visited at least a second before an earlier step's, where the model
        # reported them in order, is a disagreement between the two sensors: review. Only for pairs the expert's own
        # tool path visits in order (ref_began_s): where it reaches the later place first too, the places are shared
        timed = [c for c in checks if (c.get("measured") or {}).get("measurable") and c["measured"].get("began_s") is not None]
        def expert_in_order(c, d):
            if "ref_began_s" not in c["measured"] or "ref_began_s" not in d["measured"]:
                return True                  # measured before the baseline existed
            rc, rd = c["measured"]["ref_began_s"], d["measured"]["ref_began_s"]
            return rc is not None and rd is not None and not rd + 1.0 < rc
        for i, c in enumerate(timed):
            for d in timed[i + 1:]:
                if d["measured"]["began_s"] + 1.0 < c["measured"]["began_s"] and expert_in_order(c, d):
                    for x in (c, d):
                        x["disputed"] = True; x["reasons"].append("sam_order")
                        x["status_reason"] = (x.get("status_reason", "") + "; " if x.get("status_reason") else "") + \
                            f"tracking saw step {d['reference_step']}'s place visited before step {c['reference_step']}'s"
    present = [c for c in checks if c["status"] in PRESENT]
    # a step is out of order if a present step with a higher reference index starts before it, at the model's
    # clearest moments. Where other moments it listed would keep the order (order_moments, use_moments), the pair is
    # ambiguous: it goes to review, never silently in order (a rule fed by the model's output may only move a
    # result toward review)
    for c in present:
        c["order_start_s"] = c["observed_start_s"]
    at = order_moments(present) if use_moments else {c["reference_step"]: c["observed_start_s"] for c in present}
    for i, c in enumerate(present):
        for d in present[i + 1:]:
            if d["observed_start_s"] < c["observed_start_s"]:
                if at[d["reference_step"]] < at[c["reference_step"]]:
                    c["out_of_order"] = True; d["out_of_order"] = True
                else:
                    for x in (c, d):
                        x["disputed"] = True
                        if "other_moment" not in x["reasons"]:
                            x["reasons"].append("other_moment")
                            x["status_reason"] = (x.get("status_reason", "") + "; " if x.get("status_reason") else "") + \
                                "out of order at the clearest moments, in order at another moment the checker listed"
    missing = [c["reference_step"] for c in checks if c["status"] == "not_observed"]
    unclear = [c["reference_step"] for c in checks if c["status"] == "unclear"]
    disorder = [c["reference_step"] for c in checks if c["out_of_order"]]
    shortened = [c["reference_step"] for c in checks if c["shortened"]]
    disputed = [c["reference_step"] for c in checks if c["disputed"] and not c["out_of_order"]]
    different = [c["reference_step"] for c in checks if c["status"] == "done_differently"]
    if missing or disorder:
        verdict = "fail"
    elif unclear or shortened or disputed or different:
        verdict = "review"      # nothing wrong was seen for sure, but a person should look: unclear, cut short, disputed, another method
    else:
        verdict = "pass"
    v["checks"] = checks
    v["missing_steps"] = missing; v["out_of_order_steps"] = disorder; v["unclear_steps"] = unclear
    v["shortened_steps"] = shortened; v["disputed_steps"] = disputed; v["different_steps"] = different
    v["cannot_see"] = [c["cannot_see"] for c in checks if c["cannot_see"] and c["cannot_see"].lower() != "none"]
    v["verdict"] = verdict
    return v


def annotate_self_check(reference: dict, v: dict) -> dict:
    """Mark each reference step with what a check of the expert's own video found. A step not seen there has a
    checkpoint the camera cannot show, so later checks report it as unclear, never as missing."""
    by = {c["reference_step"]: c for c in v["checks"]}
    for st in reference["steps"]:
        c = by.get(st["index"])
        st["self_check"] = c.get("seen_status", c["status"]) if c else "unclear"
    return reference


def validate_procedure(p: dict) -> list[str]:
    """Cheap structural checks beyond the schema: ordering and time ranges."""
    problems = []
    steps = p.get("steps", [])
    for i, s in enumerate(steps):
        if s["index"] != i:
            problems.append(f"step {i} has index {s['index']}")
        if s["end_s"] < s["start_s"]:
            problems.append(f"step {i} ends before it starts")
        if i and s["start_s"] < steps[i - 1]["start_s"]:
            problems.append(f"step {i} starts before step {i-1}")
        if not s["objects"]:
            problems.append(f"step {i} names no objects")
    return problems
