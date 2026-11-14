"""Each file's diff in a unified diff, as a hash: how a viewed file's mark
knows its diff changed. And the blobs its index lines name: the versions a
viewer shows."""
from __future__ import annotations

import hashlib
import re
from typing import Dict, Optional, Tuple


def _unquote(s: str) -> str:
    """git quotes paths with unusual characters: "a/caf\\303\\251.txt"."""
    if not s.startswith('"'):
        return s
    esc = {"n": 10, "t": 9, "r": 13, "b": 8, "f": 12, "v": 11, "a": 7, '"': 34, "\\": 92}
    out, i, body = bytearray(), 0, s[1:-1]
    while i < len(body):
        c = body[i]
        if c != "\\":
            out += c.encode()
        elif body[i + 1] in "01234567":
            out.append(int(body[i + 1:i + 4], 8))
            i += 3
        else:
            out.append(esc.get(body[i + 1], ord(body[i + 1])))
            i += 1
        i += 1
    return out.decode(errors="replace")


def _path_of(raw: str, prefix: str = "") -> Optional[str]:
    s = _unquote(raw.rstrip("\t"))
    if s == "/dev/null":
        return None
    return s[len(prefix):] if prefix and s.startswith(prefix) else s


def _git_paths(rest: str) -> Tuple[Optional[str], Optional[str]]:
    """Both paths from "diff --git a/x b/x" (for diffs with no ---/+++ lines)."""
    if rest.startswith('"'):
        m = re.match(r'^("(?:[^"\\]|\\.)*")\s+(.*)$', rest)
        if m:
            return _path_of(m[1], "a/"), _path_of(m[2], "b/")
    # Unquoted, the same path on both sides: "a/<p> b/<p>" has <p> in each half
    # (this finds it even when <p> has " b/" in it)
    half = (len(rest) - 1) // 2
    if (len(rest) - 1) % 2 == 0 and rest[2:half] == rest[half + 3:]:
        return rest[2:half], rest[half + 3:]
    m = re.match(r"^a/(.*) b/(.*)$", rest)
    return (m[1], m[2]) if m else (rest, rest)


INDEX = re.compile(r"^index ([0-9a-f]+)\.\.([0-9a-f]+)")
SUBMODULE = " 160000"  # a header line's mode for a side that is a commit, not a file


def _files(diff: str) -> list:
    """Each file's part of a unified <diff>: its paths, whether it was deleted
    or is a submodule, its lines but the index line, and the blob ids on that
    line (None for none)."""
    blocks = []
    for line in diff.split("\n"):
        if line.startswith("diff --git "):
            old, new = _git_paths(line[11:])
            blocks.append({"old": old, "new": new, "deleted": False, "hunks": False, "lines": [line],
                           "index": None})
            continue
        if not blocks:
            continue
        b = blocks[-1]
        # Abbreviated blob ids can grow longer as the repository grows: not the diff
        if not line.startswith("index "):
            b["lines"].append(line)
        if line.startswith("@@"):
            b["hunks"] = True  # headers end here: a deleted "-- x" reads "--- x"
        if b["hunks"]:
            continue
        if line.endswith(SUBMODULE):  # "new file mode 160000", "index a..b 160000"
            b["submodule"] = True
        if line.startswith("index "):
            m = INDEX.match(line)
            b["index"] = (m[1], m[2]) if m else None
        elif line.startswith("deleted file mode"):
            b["deleted"] = True
        elif line.startswith("rename to ") or line.startswith("copy to "):
            b["new"] = _path_of(line.split(" to ", 1)[1])
        elif line.startswith("--- ") and _path_of(line[4:], "a/"):
            b["old"] = _path_of(line[4:], "a/")
        elif line.startswith("+++ ") and _path_of(line[4:], "b/"):
            b["new"] = _path_of(line[4:], "b/")
    return blocks


def _shown_path(b: dict) -> str:
    """The path viewers show (herdr/mods/difftate/diff.js): the old one for a
    deleted file, else the new one."""
    return b["old"] if b["deleted"] else b["new"]


def diff_hashes(diff: str) -> Dict[str, str]:
    """Each file's diff in a unified <diff>, as a hash: {path: sha1}. The path is
    the one viewers show. Any change to a file's diff changes its hash, even one
    that keeps the line counts."""
    return {_shown_path(b): hashlib.sha1("\n".join(b["lines"]).encode()).hexdigest() for b in _files(diff)}


def blob_ids(diff: str) -> Dict[str, Tuple[Optional[str], Optional[str]]]:
    """{path: (old blob, new blob)} from the index lines of a unified <diff>
    (made with --full-index), by the path viewers show. None for a side with
    no file (all zeros); a file with no index line (a rename or mode change
    alone) or a submodule (its sides are commits) is left out."""
    def blob(i: str) -> Optional[str]:
        return None if set(i) == {"0"} else i
    return {_shown_path(b): (blob(b["index"][0]), blob(b["index"][1])) for b in _files(diff)
            if b["index"] and not b.get("submodule")}
