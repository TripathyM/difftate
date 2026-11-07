"""The Changes context: the base, the changeset for a view, and whether a
thread's code moved or is outdated (GLOSSARY.md, Changes).

Its driven port is for reading the code: the code on an anchor's lines now,
snapshots, file versions and hunks, the checked-out branch and the changeset.
The port returns plain data; the moved-or-outdated decision stays in this
context's model.
"""
