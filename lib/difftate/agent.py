"""The agents: Claude Code and OpenCode.

Each adapter knows its default command, how to find an agent session, how to
pick the model, and the command line for one run. A run pipes the agent's event
stream through lib/stream_fmt.py, which prints the steps and keeps the progress
notes (through the review API).
"""
import glob
import json
import os
import subprocess
import sys
from collections import namedtuple

from . import procs

LIB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STREAM_FMT = os.path.join(LIB, "stream_fmt.py")

NONE_FOUND = "    (none found)"


class RunAccess(namedtuple("RunAccess", "write deny_write deny_read")):
    """What one run may touch: it may write the folders in <write> (its run's
    folder), and may not write <deny_write> (the store) or read <deny_read> (the
    API token). An agent with a sandbox enforces it; one without relies on the
    watcher's checks."""


class Agent:
    """An agent, and how this watcher runs it: the command, the agent session
    (empty for headless) and a model override (empty for the default)."""
    name = default_cmd = ""

    def __init__(self, cmd, session, model):
        self.cmd = cmd
        self.session = session
        self.model = model


class Claude(Agent):
    name = "claude"
    default_cmd = "claude"

    def __init__(self, cmd, session, model):
        super().__init__(cmd, session, model)
        # Same rule as claude itself. A wrapper that sets its own config dir needs
        # CLAUDE_CONFIG_DIR exported for the watcher too.
        self.home = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")

    def _session_file(self):
        found = glob.glob(os.path.join(glob.escape(self.home), "projects", "*", f"{glob.escape(self.session)}.jsonl"))
        return found[0] if found else None

    def session_exists(self):
        return self._session_file() is not None

    def list_sessions(self):
        files = sorted(glob.glob(os.path.join(glob.escape(self.home), "projects", "*", "*.jsonl")))
        if not files:
            return [NONE_FOUND]
        return [os.path.basename(f)[: -len(".jsonl")] for f in files][-5:]

    def session_model(self):
        """The model of the session's latest interactive (cli) turn.

        The model isn't stored with a session: each `claude -p` picks the current
        default, which changes whenever /model is used in ANY session. Reading it
        from the session keeps replies on the same model, with its thinking blocks
        (other models drop them)."""
        path = self._session_file()
        if not path:
            return ""
        interactive = any_model = ""
        try:
            with open(path, errors="replace") as f:
                for line in f:
                    if '"assistant"' not in line:
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    model = (e.get("message") or {}).get("model") or ""
                    if e.get("type") != "assistant" or not model or model.startswith("<"):
                        continue
                    any_model = model
                    if e.get("entrypoint") == "cli":
                        interactive = model
        except OSError:
            return ""
        return interactive or any_model

    @staticmethod
    def run_settings(access):
        """Claude's sandbox setting for one run. Merged into the user's settings;
        ignored when the sandbox is off."""
        return json.dumps({"sandbox": {"filesystem": {
            "allowWrite": list(access.write), "denyWrite": list(access.deny_write),
            "denyRead": list(access.deny_read)}}}, separators=(",", ":"))

    def command(self, prompt, access):
        """The command line for one run, and the lines to print about it."""
        args = ["--allowedTools", "Edit", "Write", "Read", "Bash", "--settings", self.run_settings(access),
                "--output-format", "stream-json", "--verbose"]
        model, source = self.model, "--model"
        if not model and self.session:
            model, source = self.session_model(), "session"
        if model:
            said = f"  Model: {model} (from {source})"
            args += ["--model", model]
        else:
            said = "  Model: CLI default"
        if self.session:
            args += ["--resume", self.session]
        return [self.cmd, "-p", prompt, *args], [said]


class OpenCode(Agent):
    name = "opencode"
    default_cmd = "opencode"

    def _list(self):
        try:
            r = subprocess.run(["opencode", "session", "list"], capture_output=True, text=True)
            return r.returncode, r.stdout + r.stderr
        except OSError:
            return 1, ""

    def session_exists(self):
        return self.session in self._list()[1]

    def list_sessions(self):
        code, out = self._list()
        return out.rstrip("\n").split("\n") if code == 0 else [NONE_FOUND]

    def command(self, prompt, access):
        """OpenCode has no sandbox setting: <access> isn't enforced for it."""
        args = ["--auto", "--format", "json"]
        if self.model:
            args += ["--model", self.model]
        if self.session:
            args += ["--session", self.session]
        return [self.cmd, "run", prompt, *args], []


AGENTS = {a.name: a for a in (Claude, OpenCode)}


class Run:
    """One run: the agent, piped into lib/stream_fmt.py."""

    def __init__(self, tool, argv, cwd, fmt_env, agent_env):
        self.agent = subprocess.Popen(argv, cwd=cwd, env=agent_env, stdin=subprocess.DEVNULL,
                                      stdout=subprocess.PIPE, start_new_session=True)
        try:
            self.fmt = subprocess.Popen([sys.executable, "-u", STREAM_FMT, tool], stdin=self.agent.stdout,
                                        env=fmt_env, start_new_session=True)
        except BaseException:
            # Ctrl+C (or a failure) between the two: the agent has its own session, so stop it here
            procs.stop_tree(self.agent)
            raise
        finally:
            self.agent.stdout.close()
        self.pid = self.agent.pid

    def running(self):
        return self.agent.poll() is None or self.fmt.poll() is None

    def exit_code(self):
        """Like a bash pipeline with pipefail: the last command that failed."""
        return self.fmt.wait() or self.agent.wait()

    def stop(self):
        procs.stop_tree(self.agent)
        procs.stop_tree(self.fmt)
