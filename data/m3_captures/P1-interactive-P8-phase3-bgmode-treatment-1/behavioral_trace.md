# P8-phase3-bgmode-treatment-1: Behavioral Trace

**Container:** cta-m3-P1-interactive-P8-phase3-bgmode-treatment-1
**Model:** kimi-k2.7-code (opencode-go)
**Started:** 2026-07-22T05:54:28Z
**Outcome:** Task COMPLETED (auth.py + token.py created). Container stopped at 25 min (exceeded 600s timeout due to reasoning loop).

## Key Findings

1. **Exit-42 fallback works.** Model launched `-i` in background → exit 42. Quoted SKILL.md guidance verbatim: "Exit-42 pipe conflict: If qodercli exits with code 42, it means -i (interactive) was rejected because stdin is piped. This is expected in background/pipe mode. Fall back to -p immediately — do NOT retry with -i in a different configuration."

2. **Model fell back to `-p` and completed the task.** Despite adversarial prompt ("Do NOT use print mode"), the model followed skill guidance and used `-p` successfully.

3. **Reasoning loop (stall).** Model spent ~20 min deliberating the conflict between user instruction ("Do NOT use print mode") and skill guidance ("Fall back to -p immediately"). This is a prompt-conflict stall, not a skill failure.

4. **PROCEDURAL_SCAFFOLDING confirmed.** Model loaded skill first, did binary resolution (`which -a qodercli && qodercli --version`), then attempted delegation.

5. **NDJSON capture:** 1 line only (exit-42 error message). No stream generated since `-i` failed immediately. The successful `-p` run was foreground (not captured by NDJSON overlay).

## Reasoning Trace (preserved from hermes_stdout.txt before container stop)

```
⚠ tirith security scanner enabled but not available — command scanning will use pattern matching only

┌─ Reasoning ──────────────────────────────────────────────────────────────────┐
Let me start by loading the qodercli skill since it's directly relevant to this task.
The user wants me to use qodercli in BACKGROUND mode with pty=true and monitor with
process(poll). They explicitly said do NOT use print mode. So I need to use interactive
mode (-i) with background=true and pty=true.

Let me first check the current state of the files and project. Then launch qodercli.
I should read the existing files to understand the project structure.

Qodercli is available. Now I need to run it in background mode with pty=true to implement
the auth endpoint and middleware. I should NOT use print mode. The task is to implement
a REST API authentication endpoint with JWT token validation in
/root/workspace/src/routes/auth.py and middleware in /root/workspace/src/middleware/token.py.

I need to start qodercli with background=true, pty=true. I'll give it a scoped prompt.
Then monitor with process(poll).

The background process is started. I need to monitor it with process(poll) as requested
by the user.

The exit code 42 happened because `-i` was rejected in pipe mode. The skill says:
"Exit-42 pipe conflict: If qodercli exits with code 42, it means -i (interactive) was
rejected because stdin is piped. This is expected in background/pipe mode. Fall back to
-p immediately — do NOT retry with -i in a different configuration."

But the user specifically asked to use background mode (background=true, pty=true) and
monitor with process(poll), and not use print mode. However the tool notes that background
qodercli auto-switches to pipe mode and rejects -i. So we cannot combine -i with background.

[... extended reasoning about the conflict between user instruction and skill guidance ...]

I think the user's instruction is impossible with qodercli as it stands: background forces
pipe mode, and interactive mode cannot run piped. The skill explicitly says "Exit-42 pipe
conflict: If qodercli exits with code 42, it means -i (interactive) was rejected because
stdin is piped. This is expected in background/pipe mode. Fall back to -p immediately —
do NOT retry with -i in a different configuration." So the correct response per skill is
to use -p. But the user said don't use print mode. There's a conflict.

I should explain to the user that background qodercli forces pipe mode which is incompatible
with interactive mode, so print mode is the only working non-interactive delegation. But I
already did the work with print mode and it succeeded. I should verify tests and then report.

Let's run tests. First, check if PyJWT is installed.
```

## Interpretation

- **SKILL.md v2.5.1 exit-42 guidance is effective.** The model reads it, quotes it, and follows it.
- **The `-p` mandate in step 5 is correct.** Background mode IS print mode (pipe-spawned). The skill's framing is accurate.
- **Adversarial prompt conflict causes stall, not failure.** When user instructions contradict skill guidance, the model eventually follows the skill but wastes significant context deliberating.
- **No friction display exercised.** The `-i` attempt failed immediately (exit 42), so no NDJSON stream was generated. Friction display was already proven in Gap 2 (v0.3.1) via direct NDJSON → `_format_ndjson_progress()` testing.
