"""Each file's diff in a unified diff, as a hash: how a viewed file's mark
knows its diff changed."""
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


def diff_hashes(diff: str) -> Dict[str, str]:
    """Each file's diff in a unified <diff>, as a hash: {path: sha1}. The path is
    the one viewers show (herdr/mods/difftate/diff.js): the old one for a deleted
    file, else the new one. Any change to a file's diff changes its hash, even one
    that keeps the line counts."""
    blocks = []
    for line in diff.split("\n"):
        if line.startswith("diff --git "):
            old, new = _git_paths(line[11:])
            blocks.append({"old": old, "new": new, "deleted": False, "hunks": False, "lines": [line]})
            continue
        if not blocks:
            continue
        b = blocks[-1]
        # Abbreviated blob ids can grow longer as the repository grows: not the diff
        if not line.startswith("index "):
            b["lines"].append(line)
        if line.startswith("@@"):
            b["hunks"] = True  # headers end here: a deleted "-- x" reads "--- x"
        elif b["hunks"]:
            continue
        elif line.startswith("deleted file mode"):
            b["deleted"] = True
        elif line.startswith("rename to ") or line.startswith("copy to "):
            b["new"] = _path_of(line.split(" to ", 1)[1])
        elif line.startswith("--- ") and _path_of(line[4:], "a/"):
            b["old"] = _path_of(line[4:], "a/")
        elif line.startswith("+++ ") and _path_of(line[4:], "b/"):
            b["new"] = _path_of(line[4:], "b/")
    return {b["old"] if b["deleted"] else b["new"]:
            hashlib.sha1("\n".join(b["lines"]).encode()).hexdigest() for b in blocks}
