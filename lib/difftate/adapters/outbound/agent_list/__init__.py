"""The machine's agent list: which coding agents can reply, and which is the
default (ADR 0008). A TOML file in the difftate home, agents.toml:

    default = "personal"

    [agents.personal]
    tool = "claude"                                   # claude or opencode
    cmd = "ccp"                                       # a program on PATH, or its full path
    env = { CLAUDE_CONFIG_DIR = "~/.claude-personal" } # what it needs in its environment (optional)
    model = "claude-opus-5-5"                         # optional: the coding agent's own default

There is no default coding agent: with no file, nothing replies. `tool` and `cmd` are
required; `cmd` is a program, never a shell alias or function (its variables go
in `env`). A list of one agent needs no `default` line; a longer one does. The
file is read again each time a run starts, so a change to it needs no restart.
"""
from __future__ import annotations

import os
import tomllib
from typing import Dict, List, NamedTuple, Optional, Sequence

TOOLS = ("claude", "opencode")
FILE = "agents.toml"


class AgentListError(Exception):
    """The list, or a name asked of it, is wrong; the message says what."""


class Agent(NamedTuple):
    name: str
    tool: str
    cmd: str
    env: Dict[str, str]
    model: str


class AgentList(NamedTuple):
    path: str
    agents: Sequence[Agent]
    default: str

    @property
    def names(self) -> List[str]:
        return [a.name for a in self.agents]

    def get(self, name: str) -> Agent:
        for agent in self.agents:
            if agent.name == name:
                return agent
        raise AgentListError(f"no agent '{name}' in the agent list ({self.path}): {', '.join(self.names)}")


def path_of(home: str) -> str:
    return os.path.join(home, FILE)


def load(home: str, home_dir: Optional[str] = None) -> AgentList:
    """The list in the difftate folder <home> (its `~` is <home_dir>, the
    user's home by default). Raises AgentListError when the file is wrong."""
    path = path_of(home)
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        raise AgentListError(f"No agent list: write {path} to choose the coding agents that reply (see INSTALL.md)")
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise AgentListError(f"could not read the agent list {path}: {e}")

    def wrong(text: str) -> AgentListError:
        return AgentListError(f"the agent list {path}: {text}")

    home_dir = home_dir or os.path.expanduser("~")
    table = data.get("agents")
    if not isinstance(table, dict) or not table:
        raise wrong("it lists no agent: add a [agents.<name>] table")
    agents = []
    for name, entry in table.items():
        if not isinstance(entry, dict):
            raise wrong(f"agent '{name}' is not a table")
        tool, cmd, model = entry.get("tool"), entry.get("cmd"), entry.get("model", "")
        if tool is None:
            raise wrong(f"agent '{name}' needs a tool ({' or '.join(TOOLS)})")
        if tool not in TOOLS:
            raise wrong(f"agent '{name}': tool '{tool}' is not one of {', '.join(TOOLS)}")
        if not isinstance(cmd, str) or not cmd.strip():
            raise wrong(f"agent '{name}' needs a cmd (the command that starts it)")
        if not isinstance(model, str):
            raise wrong(f"agent '{name}': model is text")
        env = entry.get("env", {})
        if not isinstance(env, dict) or not all(isinstance(v, str) for v in env.values()):
            raise wrong(f"agent '{name}': env is a table of text values, such as {{ CLAUDE_CONFIG_DIR = \"~/.claude\" }}")
        agents.append(Agent(name, tool, cmd.strip(), {k: _expand(v, home_dir) for k, v in env.items()}, model))
    default = data.get("default")
    if default is None and len(agents) == 1:
        default = agents[0].name
    if default is None:
        raise wrong(f"it names no default: add default = \"<name>\" ({', '.join(a.name for a in agents)})")
    if default not in table:
        raise wrong(f"default '{default}' is not one of its agents ({', '.join(a.name for a in agents)})")
    return AgentList(path, agents, default)


def _expand(value: str, home_dir: str) -> str:
    return home_dir + value[1:] if value == "~" or value.startswith("~/") else value
