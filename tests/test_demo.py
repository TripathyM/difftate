"""Seams: the `difftate` command (`difftate demo`) and the review API of the
watcher it starts (#232, ADR 0010).

Each test has a temporary HOME and a temporary folder of its own (TMPDIR), so
the demo it makes is never the user's, and nothing here touches the real
~/.difftate or a watcher running there.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import tomllib
import unittest
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_watcher import DIFFTATE, alive, wait_for, with_folder  # noqa: E402


class DemoHarness:
    """`difftate demo` in a temporary HOME and temporary folder."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="difftate-demo-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = os.path.join(self.tmp, "home")
        self.temporary = os.path.join(self.tmp, "t")
        for d in (self.home, self.temporary):
            os.makedirs(d)
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("DIFFTATE_HOME", "DT_OPEN", "DT_INTERVAL", "DT_RUN_DIR", "CLAUDE_CONFIG_DIR",
                                 "XDG_CONFIG_HOME") and not k.startswith("GIT_")}
        self.env.update(HOME=self.home, TMPDIR=self.temporary, GIT_CONFIG_NOSYSTEM="1")
        self.demo = os.path.join(self.temporary, f"difftate-demo-{os.getuid()}")
        self.demo_home = os.path.join(self.demo, "home")
        self.demo_repo = os.path.join(self.demo, "repo")
        self.started = set()  # the pid of every watcher a test saw
        self.addCleanup(self.stop_watchers)  # before the folder is removed (cleanups run last first)

    def stop_watchers(self):
        self.watcher_pid()
        for pid in self.started:
            if alive(pid):
                os.kill(pid, signal.SIGINT)
                try:
                    wait_for("the watcher to stop", lambda: not alive(pid), 15)
                except AssertionError:
                    os.kill(pid, signal.SIGKILL)

    def watcher_pid(self):
        """The pid in the demo's api.json, or None."""
        try:
            with open(os.path.join(self.demo_home, "api.json")) as f:
                pid = json.load(f)["pid"]
        except (OSError, ValueError, KeyError):
            return None
        self.started.add(pid)
        return pid if alive(pid) else None

    def difftate(self, *args, cwd=None):
        run = subprocess.run([sys.executable, DIFFTATE, *args], cwd=cwd or self.home, env=self.env,
                             stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=90)
        self.watcher_pid()
        return run


class TheDemoCommand(DemoHarness, unittest.TestCase):
    def test_help_says_what_the_demo_is_for_and_makes_none(self):
        run = self.difftate("demo", "--help")

        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("difftate demo", run.stdout)
        self.assertIn("throwaway", run.stdout)
        self.assertIn("check a viewer", run.stdout)
        self.assertFalse(os.path.exists(self.demo))

    def test_an_argument_is_refused_and_no_demo_is_made(self):
        run = self.difftate("demo", "now")

        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("takes no argument", run.stdout)
        self.assertFalse(os.path.exists(self.demo))

    def test_it_prints_where_the_demo_is_how_to_remove_it_and_the_line_that_opens_an_editor_on_it(self):
        run = self.difftate("demo")

        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn(f"The demo review is in {self.demo}", run.stdout)
        self.assertIn(f"cd {self.demo_repo} && DIFFTATE_HOME={self.demo_home} nvim +DifftateOpen", run.stdout)
        self.assertIn(f"cd {self.demo_repo} && DIFFTATE_HOME={self.demo_home} difftate browser", run.stdout)
        self.assertIn(f"DIFFTATE_HOME={self.demo_home} difftate stop && rm -rf {self.demo}", run.stdout)

    def test_a_second_run_replaces_the_first_demo_and_its_watcher(self):
        self.assertEqual(self.difftate("demo").returncode, 0)
        first = self.watcher_pid()
        left_over = os.path.join(self.demo_repo, "a-broken-try.txt")
        with open(left_over, "w") as f:
            f.write("mine\n")

        # From inside the demo itself, as from a terminal an editor opened there
        self.env["DIFFTATE_HOME"] = self.demo_home
        run = self.difftate("demo", cwd=self.demo_repo)

        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertFalse(alive(first), "the earlier demo's watcher is stopped")
        self.assertTrue(self.watcher_pid())
        self.assertNotEqual(self.watcher_pid(), first)
        self.assertFalse(os.path.exists(left_over))

    def test_it_replaces_a_demo_whose_watcher_was_already_stopped(self):
        self.assertEqual(self.difftate("demo").returncode, 0)
        first = self.watcher_pid()
        os.kill(first, signal.SIGINT)
        wait_for("the watcher to stop", lambda: not alive(first))

        run = self.difftate("demo")

        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_it_removes_nothing_through_a_link_where_the_demo_goes(self):
        mine = os.path.join(self.tmp, "mine")
        os.makedirs(mine)
        open(os.path.join(mine, "keep.txt"), "w").close()
        os.symlink(mine, self.demo)

        run = self.difftate("demo")

        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn(f"{self.demo} is not a folder of yours", run.stdout)
        self.assertEqual(os.listdir(mine), ["keep.txt"])


class TheDemoReview(DemoHarness, unittest.TestCase):
    """What the demo's watcher answers through the review API."""

    def setUp(self):
        super().setUp()
        run = self.difftate("demo")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def api(self, method, path, payload=None):
        with open(os.path.join(self.demo_home, "api.json")) as f:
            port = json.load(f)["port"]
        with open(os.path.join(self.demo_home, "token")) as f:
            token = f.read().strip()
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}{with_folder(path, self.demo_repo)}", method=method,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=10) as r:
            return json.loads(r.read())

    def test_its_watcher_serves_the_review_of_a_branch_with_a_few_changed_files(self):
        review = self.api("GET", "/api/review")
        diff = self.api("GET", "/api/changeset")["diff"]

        self.assertEqual((review["branch"], review["base"], review["folder"], review["warnings"]),
                         ("demo-languages", "main", self.demo_repo, []))
        self.assertEqual([line.split(" b/")[1] for line in diff.splitlines() if line.startswith("diff --git ")],
                         ["README.md", "greet.py", "greetings.lock", "languages.py", "test_greet.py"])

    def thread(self, example):
        """The thread whose first comment starts "<example>:"."""
        [found] = [t for t in self.api("GET", "/api/threads")
                   if t["comments"][0]["body"].startswith(f"{example}:")]
        return found

    def code_in_the_file(self, anchor):
        """What the anchor's file has on its lines now."""
        with open(os.path.join(self.demo_repo, anchor["file"])) as f:
            return "\n".join(f.read().split("\n")[anchor["startLine"] - 1:anchor["endLine"]])

    def test_it_has_a_thread_on_one_line(self):
        thread = self.thread("One line")

        anchor = thread["anchor"]
        self.assertEqual((anchor["file"], anchor["startLine"], anchor["endLine"], thread["outdated"], thread["status"]),
                         ("greet.py", 5, 5, False, "open"))
        self.assertEqual(self.code_in_the_file(anchor), "    word = GREETINGS.get(language, GREETINGS[FALLBACK])")
        self.assertEqual(anchor["code"], self.code_in_the_file(anchor))

    def test_it_has_a_thread_on_a_range_of_lines(self):
        thread = self.thread("A range")

        anchor = thread["anchor"]
        self.assertEqual((anchor["file"], anchor["startLine"], anchor["endLine"], thread["outdated"], thread["status"]),
                         ("languages.py", 3, 7, False, "open"))
        self.assertEqual(anchor["code"], self.code_in_the_file(anchor))
        self.assertTrue(anchor["code"].startswith("GREETINGS = {"))

    def test_no_run_starts_the_review_is_batched_and_the_comments_are_held(self):
        mode = self.api("GET", "/api/mode")

        self.assertEqual(mode["mode"], "batched")
        self.assertEqual(self.thread("One line")["state"], "held")
        self.assertIn(self.thread("A range")["id"], mode["held"])
        self.assertEqual({c["author"] for t in self.api("GET", "/api/threads") for c in t["comments"]}
                         - {"agent"}, {"reviewer"}, "no note: no run wrote one")

    def test_the_coding_agent_replied_in_a_thread(self):
        thread = self.thread("A reply")

        self.assertEqual((thread["anchor"]["file"], thread["status"], thread["state"]),
                         ("test_greet.py", "open", "replied"))
        self.assertEqual([(c["author"], c["kind"]) for c in thread["comments"]],
                         [("reviewer", "comment"), ("agent", "reply")])
        self.assertIn("xx", thread["comments"][1]["body"])

    def test_it_has_a_resolved_thread(self):
        thread = self.thread("Resolved")

        self.assertEqual((thread["anchor"]["file"], thread["status"], thread["state"], thread["outdated"]),
                         ("greet.py", "resolved", None, False))

    def git(self, *args):
        return subprocess.run(["git", "-C", self.demo_repo, *args], check=True, capture_output=True, text=True,
                              env=self.env).stdout

    def test_it_has_a_thread_that_a_later_commit_made_outdated(self):
        thread = self.thread("Soon outdated")

        anchor = thread["anchor"]
        self.assertEqual((anchor["file"], thread["status"], thread["outdated"]), ("greet.py", "open", True),
                         "outdated by the time difftate demo ends")
        self.assertEqual(anchor["code"], '    return f"{word}, {name}"')
        self.assertIn(anchor["code"], self.git("show", f"{anchor['commit']}:greet.py"))
        self.assertNotIn(anchor["code"], self.git("show", "HEAD:greet.py"))
        self.assertNotEqual(self.git("rev-parse", "HEAD").strip(), anchor["commit"], "a commit changed it")
        self.assertEqual([t["comments"][0]["body"].split(":")[0] for t in self.api("GET", "/api/threads")
                          if t["outdated"]], ["Soon outdated"], "no other thread is outdated")

    def test_it_has_a_viewed_file(self):
        self.assertEqual(self.api("GET", "/api/viewed"), {"files": ["README.md"]})

    def test_it_has_a_review_path_with_stops_a_key_stop_a_side_file_and_a_skipped_file(self):
        path = self.api("GET", "/api/review-path")["path"]

        def flat(stops):
            return [s for stop in stops for s in [stop, *flat(stop["children"])]]

        stops = flat(path["stops"])
        self.assertEqual([(s["number"], s["file"], s["key"]) for s in stops],
                         [("1", "greet.py", True), ("1.1", "test_greet.py", False), ("2", "README.md", False)])
        self.assertTrue(all(s["questions"] for s in stops), "each stop has its questions")
        self.assertEqual([f["file"] for f in stops[0]["side_files"]], ["languages.py"])
        self.assertEqual([f["file"] for f in path["skipped"]], ["greetings.lock"])
        self.assertEqual(path["not_on_the_path"], [], "the path names every changed file")
        self.assertEqual(self.api("GET", "/api/review")["warnings"], [])

    def test_the_review_path_is_not_one_of_the_changes(self):
        self.assertNotIn("review-path.md", self.api("GET", "/api/changeset")["diff"])
        self.assertEqual(self.git("status", "--porcelain"), "")
    def test_its_own_agent_list_names_one_agent_whose_command_does_nothing(self):
        with open(os.path.join(self.demo_home, "agents.toml"), "rb") as f:
            agents = tomllib.load(f)

        self.assertEqual(agents, {"agents": {"demo": {"tool": "claude", "cmd": "/usr/bin/true"}}})
        self.assertEqual(self.api("GET", "/api/agent"), {"agent": "demo", "source": "machine", "names": ["demo"]})


class AReviewersGitConfig(DemoHarness, unittest.TestCase):
    def test_nothing_in_it_changes_the_demo(self):
        hooks = os.path.join(self.tmp, "hooks")
        os.makedirs(hooks)
        for name in ("pre-commit", "commit-msg", "post-checkout"):
            path = os.path.join(hooks, name)
            with open(path, "w") as f:
                f.write("#!/bin/sh\nexit 1\n")
            os.chmod(path, 0o755)
        ignored = os.path.join(self.tmp, "ignored")
        with open(ignored, "w") as f:
            f.write("*.lock\ntest_*\n")
        with open(os.path.join(self.home, ".gitconfig"), "w") as f:
            f.write(f"[commit]\n\tgpgsign = true\n[gpg]\n\tprogram = false\n[core]\n\thooksPath = {hooks}\n"
                    f"\texcludesFile = {ignored}\n[difftate]\n\tagent = mine\n[init]\n\tdefaultBranch = trunk\n")
        # As from a git hook of another repository
        self.env.update(GIT_DIR=os.path.join(self.tmp, "elsewhere"), GIT_WORK_TREE=self.tmp)

        run = self.difftate("demo")

        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


# Loaded by every Python process of a test that puts it on PYTHONPATH (difftate, then the
# watcher it starts): it logs each process, and each call that names a path under WATCHED
AUDIT = """
import os, sys
log, watched = os.environ["AUDIT_LOG"], os.environ["AUDIT_WATCHED"]
def note(text):
    fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT)
    os.write(fd, (text + "\\n").encode())
    os.close(fd)
def hook(event, args):
    for arg in args:
        if isinstance(arg, str) and (arg == watched or arg.startswith(watched + os.sep)):
            note(f"touched {event} {arg}")
note(f"process {os.getpid()}")
sys.addaudithook(hook)
"""


def snapshot(folder):
    """Everything in <folder>: each entry's permissions, time of last change and content."""
    found = {}
    for top, folders, files in os.walk(folder):
        for name in ["", *folders, *files]:
            path = os.path.join(top, name) if name else top
            info = os.lstat(path)
            content = None
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    content = f.read()
            found[os.path.relpath(path, folder)] = (info.st_mode, info.st_mtime_ns, content)
    return found


class TheReviewersOwnDifftateFolder(DemoHarness, unittest.TestCase):
    def a_difftate_folder(self, folder):
        """One that looks in use: an agent list, a watcher's files and review history."""
        os.makedirs(os.path.join(folder, "history"))
        for name, text in (("agents.toml", 'default = "mine"\n[agents.mine]\ntool = "claude"\ncmd = "/usr/bin/true"\n'),
                           ("token", "my-token\n"), ("api.json", json.dumps({"pid": os.getppid(), "port": 9})),
                           ("folders.json", "[]"), ("log", "my log\n"),
                           (os.path.join("history", "2026-11.jsonl"), '{"mine": true}\n')):
            with open(os.path.join(folder, name), "w") as f:
                f.write(text)
        return folder

    def audit(self, watched):
        """Have every Python process of the test log what it touches under <watched>."""
        hooks = os.path.join(self.tmp, "hooks")
        os.makedirs(hooks)
        with open(os.path.join(hooks, "sitecustomize.py"), "w") as f:
            f.write(AUDIT)
        log = os.path.join(self.tmp, "audit.log")
        self.env.update(PYTHONPATH=hooks, AUDIT_LOG=log, AUDIT_WATCHED=watched)

        def lines():
            with open(log) as f:
                return f.read().splitlines()
        return lines

    def check_it_stays_untouched(self, folder):
        before = snapshot(folder)
        lines = self.audit(folder)

        first, second = self.difftate("demo"), self.difftate("demo")  # the second replaces a running one

        self.assertEqual((first.returncode, second.returncode), (0, 0), first.stdout + second.stdout)
        self.assertEqual([line for line in lines() if line.startswith("touched")], [], "never read or written")
        self.assertGreaterEqual(len({line for line in lines() if line.startswith("process")}), 4,
                                "the check ran in each difftate and each watcher")
        self.assertEqual(snapshot(folder), before)
        # The check itself sees a read
        subprocess.run([sys.executable, "-c", "import sys; open(sys.argv[1]).close()",
                        os.path.join(folder, "token")], env=self.env, check=True)
        self.assertTrue([line for line in lines() if line.startswith("touched open")])

    def test_the_difftate_folder_in_the_home_is_never_read_or_written(self):
        self.check_it_stays_untouched(self.a_difftate_folder(os.path.join(self.home, ".difftate")))

    def test_nor_is_the_one_difftate_home_names(self):
        folder = self.a_difftate_folder(os.path.join(self.tmp, "my-difftate"))
        self.env["DIFFTATE_HOME"] = folder

        self.check_it_stays_untouched(folder)


if __name__ == "__main__":
    unittest.main()
