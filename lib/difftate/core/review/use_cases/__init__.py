"""The Review's use cases, for reviewing: one plain function per file.

Each function takes the driven ports it needs first, then what the caller
asks for. The function is the driving port: an inbound adapter (the review
API) calls it, with the ports bound once by main.py (functools.partial).
"""
