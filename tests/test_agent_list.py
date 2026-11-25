"""Seam: the machine's agent list (#164): a config file in the difftate home
that names the coding agents, and `difftate agent`, which sets the one a
repository uses. No watcher runs here: a temporary HOME, DIFFTATE_HOME and
repository, and nothing of the real ~/.difftate is read."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIFFTATE = os.path.join(ROOT, "bin", "difftate")
sys.path.insert(0, os.path.join(ROOT, "lib"))

from difftate.adapters.outbound.agent_list import AgentListError, load  # noqa: E402

LIST = """default = "personal"

[agents.personal]
tool = "claude"
cmd = "fake-personal"
env = { CLAUDE_CONFIG_DIR = "~/.claude-personal" }

[agents.work]
tool = "claude"
cmd = "fake-work"
model = "claude-opus-5-5"

[agents.open]
tool = "opencode"
cmd = "fake-opencode"
"""


class Folder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="difftate-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = os.path.join(self.tmp, "difftate-home")
        os.makedirs(self.home)
        self.path = os.path.join(self.home, "agents.toml")

    def write(self, text):
        with open(self.path, "w") as f:
            f.write(text)


class ReadingTheList(Folder):
    def test_each_agent_is_a_name_a_coding_agent_a_command_with_its_environment_and_a_model(self):
        self.write(LIST)

        agents = load(self.home, home_dir="/home/me")

        self.assertEqual((agents.names, agents.default), (["personal", "work", "open"], "personal"))
        personal = agents.get("personal")
        self.assertEqual((personal.tool, personal.cmd, personal.model), ("claude", "fake-personal", ""))
        self.assertEqual(personal.env, {"CLAUDE_CONFIG_DIR": "/home/me/.claude-personal"}, "~ is the home")
        self.assertEqual(agents.get("work").model, "claude-opus-5-5")
        self.assertEqual(agents.get("open").tool, "opencode")

    def test_with_no_list_no_agent_replies_and_it_says_which_file_to_write(self):
        with self.assertRaises(AgentListError) as refused:
            load(self.home)

        self.assertEqual(str(refused.exception),
                         f"No agent list: write {self.path} to choose the coding agents that reply (see INSTALL.md)")

    def test_a_name_that_is_not_listed_is_refused_with_the_names(self):
        self.write(LIST)

        with self.assertRaises(AgentListError) as refused:
            load(self.home).get("nope")

        self.assertIn("no agent 'nope'", str(refused.exception))
        self.assertIn("personal, work, open", str(refused.exception))

    def test_a_list_that_is_wrong_says_what_and_where(self):
        cases = {
            "not toml [": "agents.toml",
            'default = "x"\n[agents.a]\ntool = "claude"\ncmd = "c"\n': "default 'x'",
            '[agents.a]\ntool = "gemini"\ncmd = "c"\n': "tool 'gemini'",
            '[agents.a]\ntool = "claude"\n': "cmd",
            '[agents.a]\ncmd = "c"\n': "agent 'a' needs a tool (claude or opencode)",
            '[agents.a]\ntool = "claude"\ncmd = "c"\nenv = { N = 1 }\n': "env",
            '[agents.a]\ntool = "claude"\ncmd = "c"\n[agents.b]\ntool = "claude"\ncmd = "c"\n': "no default",
        }
        for text, said in cases.items():
            with self.subTest(text=text):
                self.write(text)
                with self.assertRaises(AgentListError) as refused:
                    load(self.home)
                self.assertIn(said, str(refused.exception))
                self.assertIn(self.path, str(refused.exception))

    def test_a_single_agent_is_the_default_without_saying_so(self):
        self.write('[agents.only]\ntool = "claude"\ncmd = "c"\n')

        self.assertEqual(load(self.home).default, "only")


class TheRepositorysAgent(Folder):
    def setUp(self):
        super().setUp()
        self.repo = os.path.join(self.tmp, "repo")
        home = os.path.join(self.tmp, "home")
        os.makedirs(self.repo)
        os.makedirs(home)
        with open(os.path.join(home, ".gitconfig"), "w") as f:
            f.write("[user]\n\tname = Test\n\temail = test@example.com\n")
        self.env = {k: v for k, v in os.environ.items() if k not in ("DIFFTATE_HOME", "XDG_CONFIG_HOME")}
        self.env.update(HOME=home, DIFFTATE_HOME=self.home, GIT_CONFIG_NOSYSTEM="1")
        self.git("init", "-q", "-b", "main")
        self.git("commit", "-q", "--allow-empty", "-m", "first")
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        for name in ("fake-personal", "fake-work", "fake-opencode"):  # the commands of LIST exist
            path = os.path.join(self.bin, name)
            with open(path, "w") as f:
                f.write("#!/bin/sh\n")
            os.chmod(path, 0o755)
        self.env["PATH"] = os.pathsep.join([self.bin, os.environ["PATH"]])
        self.write(LIST)

    def git(self, *args, folder=None):
        return subprocess.run(["git", "-C", folder or self.repo, *args], check=True, capture_output=True, text=True,
                              env=self.env).stdout.strip()

    def difftate(self, *args, folder=None):
        run = subprocess.run([sys.executable, DIFFTATE, "agent", *args], cwd=folder or self.repo, env=self.env,
                             stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        return run.returncode, run.stdout + run.stderr

    def test_with_no_name_it_says_the_machine_default_when_the_repository_has_none(self):
        code, out = self.difftate()

        self.assertEqual(code, 0, out)
        self.assertIn("personal", out)
        self.assertIn("machine", out)

    def test_a_name_sets_the_repositorys_agent_in_its_git_config_and_never_in_a_commit(self):
        code, out = self.difftate("work")

        self.assertEqual(code, 0, out)
        self.assertEqual(self.git("config", "--local", "difftate.agent"), "work")
        self.assertEqual(self.git("status", "--porcelain"), "", "nothing to commit")
        code, out = self.difftate()
        self.assertIn("work", out)
        self.assertIn("repository", out)

    def test_its_worktrees_share_it(self):
        worktree = os.path.join(self.tmp, "wt")
        self.git("worktree", "add", "-q", "-b", "other", worktree)
        code, out = self.difftate("open")
        self.assertEqual(code, 0, out)

        code, out = self.difftate(folder=worktree)

        self.assertIn("open", out)
        self.assertIn("repository", out)

    def test_an_unknown_name_is_refused_with_the_names_and_sets_nothing(self):
        code, out = self.difftate("nope")

        self.assertEqual(code, 1, out)
        self.assertIn("no agent 'nope'", out)
        self.assertIn("personal, work, open", out)
        self.assertEqual(subprocess.run(["git", "-C", self.repo, "config", "--local", "difftate.agent"], env=self.env,
                                        capture_output=True).returncode, 1, "no setting")

    def test_an_agent_whose_command_isnt_found_is_refused(self):
        os.remove(os.path.join(self.bin, "fake-work"))

        code, out = self.difftate("work")

        self.assertEqual(code, 1, out)
        self.assertIn("command 'fake-work' not found", out)

    def test_a_cmd_that_is_only_a_shell_alias_is_refused_and_says_what_to_write(self):
        # An alias to a real program, which an interactive zsh would follow
        with open(os.path.join(self.env["HOME"], ".zshrc"), "w") as f:
            f.write(f"alias only-an-alias={os.path.join(self.bin, 'fake-work')}\n")
        self.write('[agents.work]\ntool = "claude"\ncmd = "only-an-alias"\n')

        code, out = self.difftate("work")

        self.assertEqual(code, 1, out)
        self.assertIn("command 'only-an-alias' not found on PATH (a shell alias can't be a cmd: "
                      "write its program and env)", out)

    def test_a_full_path_is_a_command(self):
        self.write(f'[agents.work]\ntool = "claude"\ncmd = "{os.path.join(self.bin, "fake-work")}"\n')

        code, out = self.difftate("work")

        self.assertEqual(code, 0, out)

    def test_with_no_list_it_says_which_file_to_write(self):
        os.remove(self.path)

        code, out = self.difftate()

        self.assertEqual(code, 1, out)
        self.assertIn(f"No agent list: write {self.path}", out)

    def test_a_setting_that_names_an_agent_gone_from_the_list_is_said(self):
        self.git("config", "difftate.agent", "gone")

        code, out = self.difftate()

        self.assertEqual(code, 1, out)
        self.assertIn("'gone'", out)
        self.assertIn("personal, work, open", out)

    def test_outside_a_repository_it_says_so(self):
        code, out = self.difftate(folder=self.tmp)

        self.assertEqual(code, 1, out)
        self.assertIn("not a checked-out folder of a git repository", out)

    def test_the_flags_that_chose_the_agent_are_gone(self):
        for flag in ("--tool", "--cmd", "--model", "--interval"):
            with self.subTest(flag=flag):
                run = subprocess.run([sys.executable, DIFFTATE, flag, "x"], cwd=self.repo, env=self.env,
                                     capture_output=True, text=True, timeout=60)
                self.assertEqual(run.returncode, 1, run.stdout)
                self.assertIn(f"Unknown flag: {flag}", run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
