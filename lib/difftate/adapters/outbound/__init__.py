"""Driven adapters: the core calls them through its ports (ADR 0003).

local_store/ and memory_store/ are for keeping the review. history_files/ is
for recording review history. git/ is for reading the code. terminal/ is for
reporting. coding_agents/ is for asking the coding agent: claude_code/ and
opencode/, which share reply_channel/ (the run's folder and dt-reply).
"""
