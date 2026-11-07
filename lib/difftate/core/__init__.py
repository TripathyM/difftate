"""The core: difftate's rules, with no technology (ADR 0003).

It holds the Review, a thread following its code, Dispatch, the prompt and the
review history, in the words of GLOSSARY.md. It reaches git, HTTP, processes,
files and the terminal only through the ports it defines. Nothing here imports
difftate.adapters, subprocess, http, socket or urllib, or prints;
tests/test_core_boundary.py checks this.

One package per context: review, changes and dispatch. Each has model.py (its
types and rules), ports.py (the driven ports it needs, as typing.Protocol
classes) and use_cases/ (one plain function per file; the function is the
driving port).
"""
