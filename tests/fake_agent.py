#!/usr/bin/env python3
"""A fake Claude Code for watcher tests, swapped in through `--cmd`.

Called like `claude -p <prompt> ... --output-format stream-json --verbose`.
It prints Claude-style events, then answers every thread under "Reply to these
threads" with the `dt-reply` command the prompt names (and no other way).

Controlled through FAKE_AGENT_DIR (a folder the test owns):
  pid      written at start: this process's id
  args     written at start: its command-line arguments, as JSON
  run_dir  written at start: the run's folder it was given ($DT_RUN_DIR)
  prompt   written at start: the prompt it was sent
  prompts  one line appended per run: the prompt as JSON
  go       the coding agent waits for this file before it replies, so a test can see
           the thread while the run is working
  rogue    a thread id: the agent also writes a reply to it straight into the
           run's folder, without dt-reply (an agent breaking the rules)
  linger   while this file exists, the coding agent waits after its replies for
           the file "finish" before the run ends, so a test can stop the
           watcher between the two
  silent   while this file exists, the coding agent replies to no thread; when it
           lists run numbers ("2" or "1,3"), only in those runs
  error    while this file exists, the run ends with an error result whose
           message is the file's text
  crash    run numbers ("3" or "1,3"): in those runs the coding agent exits at
           once with an error, no event and no reply
"""
import json
import os
import re
import shlex
import subprocess
import sys
import time

GATE_TIMEOUT_S = 30


def emit(event):
    print(json.dumps(event), flush=True)


def this_run(folder):
    """This run's number (1 for the first), from the prompts so far."""
    with open(os.path.join(folder, "prompts")) as f:
        return sum(1 for _ in f)


def runs_listed(path):
    with open(path) as f:
        return [int(n) for n in f.read().split(",") if n.strip()]


def main():
    args = sys.argv[1:]
    prompt = args[args.index("-p") + 1] if "-p" in args else ""
    folder = os.environ.get("FAKE_AGENT_DIR", "")
    if folder:
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "pid"), "w") as f:
            f.write(str(os.getpid()))
        with open(os.path.join(folder, "args"), "w") as f:
            json.dump(args, f)
        with open(os.path.join(folder, "run_dir"), "w") as f:
            f.write(os.environ.get("DT_RUN_DIR", ""))
        with open(os.path.join(folder, "prompt"), "w") as f:
            f.write(prompt)
        with open(os.path.join(folder, "prompts"), "a") as f:
            f.write(json.dumps(prompt) + "\n")

    crash = os.path.join(folder, "crash") if folder else ""
    if crash and os.path.exists(crash) and this_run(folder) in runs_listed(crash):
        sys.exit(1)

    mine = prompt.split("## Other open threads")[0]
    ids = re.findall(r"^### Thread ([0-9a-f]{8})", mine, re.M)

    emit({"type": "system", "subtype": "init", "session_id": "fake-session", "model": "fake-model"})
    emit({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Read", "input": {"file_path": "app.py"}}]}})

    gate = os.path.join(folder, "go") if folder else ""
    deadline = time.time() + GATE_TIMEOUT_S
    while gate and not os.path.exists(gate) and time.time() < deadline:
        time.sleep(0.05)

    silent = os.path.join(folder, "silent") if folder else ""
    if silent and os.path.exists(silent):
        runs = runs_listed(silent)
        if not runs or this_run(folder) in runs:
            ids = []
    # The reply command, as the prompt's rules name it: `with: <dt-reply> <thread> "<answer>"`
    # (the path is shell-quoted, so it may hold spaces)
    found = re.search(r"with: (.+?) <thread> \"<answer>\"", prompt)
    dt_reply = shlex.split(found.group(1))[0] if found else ""
    rogue = os.path.join(folder, "rogue") if folder else ""
    if rogue and os.path.exists(rogue):
        with open(rogue) as f:
            target = f.read().strip()
        with open(os.path.join(os.environ["DT_RUN_DIR"], "replies", "0-rogue.json"), "w") as f:
            json.dump({"thread": target, "body": "A reply nobody asked for."}, f)
    for tid in ids if dt_reply else []:
        subprocess.run([dt_reply, tid, f"Fake answer to {tid}."], check=True, stdout=subprocess.DEVNULL)
    if folder and os.path.exists(os.path.join(folder, "linger")):
        deadline = time.time() + GATE_TIMEOUT_S
        while not os.path.exists(os.path.join(folder, "finish")) and time.time() < deadline:
            time.sleep(0.05)
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": f"Replied to {len(ids)} thread(s)."}]}})
    error = os.path.join(folder, "error") if folder else ""
    if error and os.path.exists(error):
        with open(error) as f:
            emit({"type": "result", "subtype": "error", "is_error": True, "result": f.read(), "modelUsage": {}})
        return
    emit({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.0123, "modelUsage": {}})


main()
