"""The coding agents, for asking the coding agent (ForAskingTheCodingAgent):
claude_code/ and opencode/.

Each coding agent is one folder: its command line, how it finds an agent
session and picks the model, its sandbox settings, and the reader of its
event stream. They share coding_agent.py (what every coding agent has),
reply_channel/ (the run's folder and dt-reply), events.py (one JSON event
per line), run.py (the process, read into news) and processes.py (stopping
a process and everything it started, and finding the command).
"""
from __future__ import annotations

from .claude_code import ClaudeCode
from .opencode import OpenCode
from .processes import find_command

__all__ = ["ClaudeCode", "OpenCode", "find_command"]
