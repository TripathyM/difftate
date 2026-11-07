"""The adapters: each plugs one technology into a port of the core (ADR 0003).

inbound/ holds the driving adapters, which call the core's use cases.
outbound/ holds the driven adapters, which the core calls through its ports.
The core never imports from here; main.py picks the adapters and wires them.
"""
