"""`difftate demo`: a throwaway demo review with an example of each capability,
to check a viewer against (GLOSSARY.md, Demo review; ADR 0010).

The demo folder, in the temporary folder, holds a git repository and a difftate
folder of its own, with its own watcher: nothing of the reviewer's is read or
written. The review is built through the review API, as any viewer would.
"""
import dataclasses
import os
import shlex
import shutil
import subprocess
import tempfile
import time

from . import one_watcher
from .difftate import ask, said, stop_running, with_folder
from .options import Exit

USAGE = """difftate demo — Make a throwaway demo review, to check a viewer against.

Usage:
  difftate demo

The demo review has an example of each capability: threads on one line and on a range of
lines, an outdated thread, a thread the coding agent replied in, a resolved thread, a viewed
file and a review path. It is batched, so comments are held and no run starts until you
submit. Its agent list names one agent whose command does nothing: nothing real replies.

It lives in a folder of its own in the temporary folder, with a git repository, a difftate
folder and a watcher: your own difftate folder is never read or written. Running it again
replaces the earlier demo. It prints how to open your editor on it, and how to remove it."""

BASE = "main"
BRANCH = "demo-languages"
# How long the demo waits for its watcher to find the outdated thread
OUTDATING_S = 30
# The demo's whole agent list: its command does nothing, so nothing real ever replies
AGENT_LIST = '[agents.demo]\ntool = "claude"\ncmd = "true"\n'

# The files on the base, then what each commit of the branch writes
ON_BASE = {
    "README.md": "# greeter\n\nGreets people by name.\n",
    "greet.py": 'def greet(name):\n    return "Hello, " + name\n\n\nif __name__ == "__main__":\n'
                '    print(greet("world"))\n',
}
FIRST_COMMIT = ("Greet in more than one language", {
    "README.md": '# greeter\n\nGreets people by name.\nAsk for a language by its code: `greet("Ada", "fr")`.\n',
    "greet.py": 'from languages import FALLBACK, GREETINGS\n\n\ndef greet(name, language=FALLBACK):\n'
                '    word = GREETINGS.get(language, GREETINGS[FALLBACK])\n    return f"{word}, {name}"\n\n\n'
                'if __name__ == "__main__":\n    print(greet("world"))\n',
    "greetings.lock": "# Generated: do not edit\nen 1\nfr 1\nes 1\n",
    "languages.py": 'FALLBACK = "en"\n\nGREETINGS = {\n    "en": "Hello",\n    "fr": "Bonjour",\n'
                    '    "es": "Hola",\n}\n',
    "test_greet.py": 'from greet import greet\n\n\ndef test_greets_in_the_language_asked_for():\n'
                     '    assert greet("Ada", "fr") == "Bonjour, Ada"\n\n\n'
                     'def test_falls_back_to_english():\n    assert greet("Ada", "xx") == "Hello, Ada"\n',
})
SECOND_COMMIT = ("Greet a nameless caller as a friend", {
    "greet.py": FIRST_COMMIT[1]["greet.py"].replace('{name}"', '{name or \'friend\'}"'),
})
# Written beside the files and kept out of git, so it is no change of its own
REVIEW_PATH = """## 1 `greet.py:4-6` ★

### What does this change?
`greet()` takes a language code. See "The fallback".

### Side file: `languages.py`
The table `greet()` looks the word up in.

## 1.1 `test_greet.py`

### What do the tests show?
A language the table has, and one it doesn't.

## 2 `README.md`

### What does a caller need to know?
How to ask for a language.

## Section: The fallback
A code the table doesn't have gets the English word.

## Skipped
- `greetings.lock` — generated
"""


def run_demo(argv, wiring):
    """Run `difftate demo` as <argv> says (wiring.Wiring); the exit code."""
    try:
        if argv and argv[0] in ("--help", "-h"):
            raise Exit(0, USAGE)
        if argv:
            raise Exit(1, f"Error: demo takes no argument\n{USAGE}")
        return _make(wiring)
    except Exit as e:
        if e.message:
            print(e.message)
        return e.code


def _make(wiring):
    # The real path: the watcher names folders by theirs
    temporary = os.path.realpath(tempfile.gettempdir())
    demo = os.path.join(temporary, f"difftate-demo-{os.getuid()}")  # a temporary folder may be shared
    home, repo = os.path.join(demo, "home"), os.path.join(demo, "repo")
    # From here on, the demo's difftate folder is the only one: the wiring's calls
    # name it, and the watcher started below gets it from its environment
    os.environ["DIFFTATE_HOME"] = home
    # A git hook's GIT_DIR (and the like) would point git, the watcher's too, at another repository
    for name in [n for n in os.environ if n.startswith("GIT_")]:
        del os.environ[name]
    wiring = dataclasses.replace(wiring, difftate_home=home)
    os.chdir(temporary)  # not in the earlier demo: the watcher starts where this process is
    _remove_earlier(wiring, demo)
    os.mkdir(demo, 0o700)
    os.mkdir(home, 0o700)
    _write(home, "agents.toml", AGENT_LIST)
    try:
        _make_repository(repo)
        pid = one_watcher.ensure(home, wiring.running_watcher, lambda: wiring.start_watcher(["--interval", "1"]))
        _build_review(wiring, repo)
    except BaseException:  # Ctrl+C too: its watcher may be running
        print(f"The demo in {demo} is not complete. Its watcher's log is {os.path.join(home, 'log')}.\n"
              f"Remove it: {_removal(demo, home)}")
        raise
    _print_where(demo, home, repo, pid)
    return 0


def _removal(demo, home):
    """The line that stops the demo's watcher, then removes the demo."""
    return f"DIFFTATE_HOME={shlex.quote(home)} difftate stop && rm -rf {shlex.quote(demo)}"


def _remove_earlier(wiring, demo):
    """Stop the earlier demo's watcher and remove its folder, if there is one."""
    if not os.path.lexists(demo):
        return
    if os.path.islink(demo) or not os.path.isdir(demo) or os.lstat(demo).st_uid != os.getuid():
        raise Exit(1, f"Error: {demo} is not a folder of yours: remove it, then run difftate demo again")
    stop_running(wiring, wiring.running_watcher(wiring.difftate_home))
    shutil.rmtree(demo)


def _make_repository(repo):
    """The demo's repository, on its branch. Its own git config keeps the
    reviewer's (signing, hooks, ignored files, agent) out of it."""
    os.mkdir(repo)
    _git(repo, "init", "-q", "--template=", "-b", BASE)
    for name, value in (("user.name", "Demo reviewer"), ("user.email", "demo@example.invalid"),
                        ("commit.gpgsign", "false"), ("core.hooksPath", os.devnull),
                        ("core.excludesFile", os.devnull)):
        _git(repo, "config", name, value)
    _commit(repo, "A greeter", ON_BASE)
    _git(repo, "checkout", "-q", "-b", BRANCH)
    _commit(repo, *FIRST_COMMIT)
    os.makedirs(os.path.join(repo, ".git", "info"), exist_ok=True)
    _write(repo, os.path.join(".git", "info", "exclude"), "review-path.md\n")
    _write(repo, "review-path.md", REVIEW_PATH)


def _git(repo, *args):
    done = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if done.returncode != 0:
        raise Exit(1, f"Error: the demo's repository: git {args[0]} failed: {done.stderr.strip()}")


def _write(folder, path, text):
    """In one step: the watcher, polling meanwhile, must not see half a file, or the
    threads on it would become outdated."""
    target = os.path.join(folder, path)
    with open(target + ".new", "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(target + ".new", target)


def _commit(repo, message, files):
    for path, text in files.items():
        _write(repo, path, text)
    _git(repo, "add", "--all")
    _git(repo, "commit", "-q", "-m", message)


def _build_review(wiring, repo):
    def call(method, path, payload=None):
        status, answer = ask(wiring, method, with_folder(path, repo), payload)
        if status != 200:
            raise Exit(1, f"Error: the demo review: {method} {path}: {said(answer, status)}")
        return answer

    def open_thread(body, file, first, last=None):
        """A thread on <file> from the line <first> to the line <last> (the same line
        when none is given), each given by its text."""
        return call("POST", "/api/threads", {"anchor": _anchor(repo, file, first, last or first), "body": body})["id"]

    call("GET", "/api/review")  # the first request that names the folder adds it
    # Batched, so the comments are held: no run starts, and nothing replies on its own
    call("PUT", "/api/mode", {"mode": "batched"})
    open_thread("One line: an unknown language gets the fallback with no word about it. Is that what we want?",
                "greet.py", "    word = GREETINGS.get(language, GREETINGS[FALLBACK])")
    open_thread("A range: should this table be in a data file?", "languages.py", "GREETINGS = {", "}")
    replied = open_thread('A reply: why "xx" here?', "test_greet.py",
                          '    assert greet("Ada", "xx") == "Hello, Ada"')
    # The coding agent's reply, posted as dt-reply posts one outside a run: no agent runs
    call("POST", f"/api/threads/{replied}/comments",
         {"kind": "reply", "body": "No language has the code `xx`, so the test takes the fallback."})
    resolved = open_thread("Resolved: import only what greet() needs.", "greet.py",
                           "from languages import FALLBACK, GREETINGS")
    call("PATCH", f"/api/threads/{resolved}/status", {"status": "resolved"})
    outdated = open_thread('Soon outdated: what does greet("") say?', "greet.py", '    return f"{word}, {name}"')
    # A commit that changes that thread's code: the watcher finds it at its next poll
    _commit(repo, *SECOND_COMMIT)
    _wait_until_outdated(call, outdated)
    call("PUT", "/api/viewed", {"file": "README.md"})


def _wait_until_outdated(call, thread_id):
    deadline = time.time() + OUTDATING_S
    while not any(t["id"] == thread_id and t["outdated"] for t in call("GET", "/api/threads")):
        if time.time() > deadline:
            raise Exit(1, f"Error: the demo review: no outdated thread after {OUTDATING_S}s ")
        time.sleep(0.1)


def _anchor(repo, file, first, last):
    with open(os.path.join(repo, file), encoding="utf-8") as f:
        lines = f.read().split("\n")
    start = lines.index(first)
    end = lines.index(last, start)
    return {"file": file, "side": "new", "startLine": start + 1, "endLine": end + 1,
            "code": "\n".join(lines[start:end + 1])}


def _print_where(demo, home, repo, pid):
    with_home = f"DIFFTATE_HOME={shlex.quote(home)}"
    print(f"The demo review is in {demo}: the branch {BRANCH} against {BASE}, with a watcher of its own (pid {pid}).\n"
          f"Open an editor on it with its difftate folder:\n"
          f"  Neovim:   cd {shlex.quote(repo)} && {with_home} nvim +DifftateOpen\n"
          f"  browser:  cd {shlex.quote(repo)} && {with_home} difftate browser\n"
          f"Remove it (`difftate demo` again makes a fresh one):\n"
          f"  {_removal(demo, home)}")
