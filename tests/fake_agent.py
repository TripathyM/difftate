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
  go       the agent waits for this file before it replies, so a test can see
           the thread while the run is working
  silent   while this file exists, the agent replies to no thread; when it
           lists run numbers ("2" or "1,3"), only in those runs
"""
import json
import os
import re
import subprocess
import sys
import time

GATE_TIMEOUT_S = 30


def emit(event):
    print(json.dumps(event), flush=True)


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
        with open(silent) as f:
            runs = [int(n) for n in f.read().split(",") if n.strip()]
        with open(os.path.join(folder, "prompts")) as f:
            this_run = sum(1 for _ in f)
        if not runs or this_run in runs:
            ids = []
    # The reply command, as the prompt's rules name it: `<path>/dt-reply <thread> "<answer>"`
    found = re.search(r"(\S*dt-reply) <thread>", prompt)
    for tid in ids if found else []:
        subprocess.run([found.group(1), tid, f"Fake answer to {tid}."], check=True, stdout=subprocess.DEVNULL)
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": f"Replied to {len(ids)} thread(s)."}]}})
    emit({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.0123, "modelUsage": {}})


main()
