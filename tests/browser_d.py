"""What the tests of layout D share: node runs one of the page's DOM-free modules (web/d/), and
gets API answers shaped like the released transcript of the review API."""
import json
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "lib", "difftate", "adapters", "inbound", "review_api", "web")
RELEASED = os.path.join(ROOT, "tests", "fixtures", "review_api_released.json")


def run_js(module, body):
    """Run <body> in node with web/d/<module>.js imported as m; "{DIFF}",
    "{STATE}", "{API}" and "{DRAFTS}" in it name web/diff.js and web/d/'s state.js, api.js and
    drafts.js. <body> prints JSON: what it printed."""
    path = "file://" + os.path.join(WEB, "d", module + ".js")
    for name, other in (("DIFF", "diff.js"), ("STATE", os.path.join("d", "state.js")),
                        ("API", os.path.join("d", "api.js")), ("DRAFTS", os.path.join("d", "drafts.js"))):
        body = body.replace(f'"{{{name}}}"', json.dumps("file://" + os.path.join(WEB, other)))
    script = f"import * as m from {json.dumps(path)};\n{body}"
    run = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=30)
    if run.returncode:
        raise AssertionError(run.stderr)
    return json.loads(run.stdout)


def released(method, path, having=bool):
    """The first answer the released transcript shows for <method> <path> that <having> accepts
    (default: not empty)."""
    with open(RELEASED) as f:
        steps = json.load(f)
    return next(s["answer"] for s in steps if s["request"][:2] == [method, path] and s["status"] == 200
                and having(s["answer"]))


def changed(path, *lines):
    """One modified file of a unified diff, as the changeset's "diff" has it."""
    return "".join(line + "\n" for line in (f"diff --git a/{path} b/{path}", f"--- a/{path}", f"+++ b/{path}",
                                            *(lines or ("@@ -1 +1 @@", "-old", "+new"))))


def answers(**changes):
    """One poll's answers, as web/d/poll.js gives them: the released transcript's, with <changes>."""
    return dict({
        "review": dict(released("GET", "/api/review"), warnings=[]),
        "mode": released("GET", "/api/mode"),
        "agent": released("GET", "/api/agent"),
        "changeset": released("GET", "/api/changeset"),
        "threads": released("GET", "/api/threads"),
        "viewed": [],
        "reviewPath": None,
        "done": released("GET", "/api/done", lambda a: not a["done"]),
    }, **changes)
