"""Changes: the base, the review's branch, and the changeset, from git.

A review is one branch against its base, like a pull request. The base is the
repository's default branch (origin/HEAD) unless --base gives another; without
an origin/HEAD, a local main or master stands in. With a detached HEAD, or on
the base branch itself, the current commit stands in for the branch.

The changeset is every change from where the branch left the base (their merge
base, as in a pull request) to the files on disk, new untracked files included.
A view shows part of it, as the same review (a thread written in any view belongs
to the review):
  ""          all changes (the default)
  <commit>    the commits after it, and the files on disk: HEAD~2 is the last two
              commits; HEAD is the uncommitted changes
  staged      what is staged (the index against HEAD)
  unstaged    what isn't staged yet (the files on disk against the index)

Code (below) says where each thread's code is now: a thread follows its code
through the changes, or is outdated.
"""
import hashlib
import os
import re
import shutil
import subprocess
import tempfile


class ChangesError(Exception):
    pass


class ViewError(ChangesError):
    """A view that isn't one: no such commit."""


NAMED_VIEWS = ("staged", "unstaged")


def need_view(cwd, view):
    """<view> as given ("" for all changes), once it is known to be a view."""
    if view is None or view == "":
        return ""
    if not isinstance(view, str):
        raise ViewError("a view is text: \"\", a commit, staged or unstaged")
    if view in NAMED_VIEWS:
        return view
    if view.startswith("-") or _git(cwd, "rev-parse", "--verify", "--quiet", f"{view}^{{commit}}") is None:
        raise ViewError(f"no view '{view}': give a commit (HEAD~2, HEAD), staged or unstaged, or nothing for all changes")
    return view


def view_name(view):
    """How the terminal names a view."""
    if not view:
        return "all changes"
    if view == "HEAD":
        return "uncommitted changes"
    if view in NAMED_VIEWS:
        return f"{view} changes"
    return f"the commits after {view}"


def _git(cwd, *args, env=None):
    r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, env=env)
    return r.stdout.strip() if r.returncode == 0 else None


def resolve_base(cwd, given=""):
    """The review's base: <given>, else the repository's default branch."""
    if given:
        if _git(cwd, "rev-parse", "--verify", "--quiet", f"{given}^{{commit}}") is None:
            raise ChangesError(f"Error: the base '{given}' is not a branch or commit in this repository")
        return given
    origin = _git(cwd, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if origin and _git(cwd, "rev-parse", "--verify", "--quiet", f"{origin}^{{commit}}"):
        return origin
    for name in ("main", "master"):
        if _git(cwd, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}"):
            return name
    raise ChangesError("Error: no default branch found (no origin/HEAD, main or master). "
                       "Pass --base <branch>, or run: git remote set-head origin --auto")


def head(cwd):
    """The commit checked out, or None in a repository with no commit yet."""
    return _git(cwd, "rev-parse", "--verify", "--quiet", "HEAD")


def _on_base(cwd, branch, base):
    full = _git(cwd, "rev-parse", "--symbolic-full-name", base) or ""
    if full == f"refs/heads/{branch}":
        return True
    # A remote's copy of the branch: origin/main is the base when main is checked out
    parts = full.split("/", 3)
    return full.startswith("refs/remotes/") and len(parts) == 4 and parts[3] == branch


def review_branch(cwd, base):
    """What the review is of: the checked-out branch, or the current commit on a
    detached HEAD or on the base branch itself."""
    branch = _git(cwd, "symbolic-ref", "--quiet", "--short", "HEAD")
    if branch and not _on_base(cwd, branch, base):
        return branch
    commit = head(cwd)
    if not commit:
        raise ChangesError("Error: the repository has no commit yet")
    return commit


def review_id(branch, base):
    """A review's id: readable, and different for every branch and base."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", branch)[:40].strip("-.") or "review"
    digest = hashlib.sha1(f"{branch}\0{base}".encode()).hexdigest()[:8]
    return f"{slug}-{digest}"


def remote_url(cwd):
    return _git(cwd, "remote", "get-url", "origin")


def changeset(cwd, base, view=""):
    """The review's changeset in <view>: {"view", "base", "commit" (where the branch
    left the base), "diff" (a unified diff, new untracked files included)}."""
    if base is None:
        raise ChangesError("no base: pass --base <branch>")
    view = need_view(cwd, view)
    commit = _git(cwd, "merge-base", base, "HEAD") or head(cwd)
    if not commit:
        raise ChangesError("the repository has no commit yet")
    if view == "staged":
        r = subprocess.run(["git", "-C", cwd, "diff", "--no-color", "--no-ext-diff", "--cached", "HEAD", "--"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise ChangesError(f"git diff failed: {r.stderr.strip()}")
        return {"view": view, "base": base, "commit": commit, "diff": r.stdout}
    against = [] if view == "unstaged" else [view or commit]
    # Untracked files show as new files: add them, intent only, to a copy of the index
    git_dir = _git(cwd, "rev-parse", "--absolute-git-dir")
    tmp = tempfile.mkdtemp(prefix="difftate-index-")
    try:
        index = os.path.join(tmp, "index")
        if git_dir and os.path.exists(os.path.join(git_dir, "index")):
            shutil.copy(os.path.join(git_dir, "index"), index)
        env = dict(os.environ, GIT_INDEX_FILE=index)
        top = _git(cwd, "rev-parse", "--show-toplevel") or cwd
        subprocess.run(["git", "-C", top, "add", "--intent-to-add", "--all"], capture_output=True, env=env)
        r = subprocess.run(["git", "-C", top, "diff", "--no-color", "--no-ext-diff", *against, "--"],
                           capture_output=True, text=True, env=env)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if r.returncode != 0:
        raise ChangesError(f"git diff failed: {r.stderr.strip()}")
    return {"view": view, "base": base, "commit": commit, "diff": r.stdout}


# ── Each file's diff ─────────────────────────────────────────────────────────
def _unquote(s):
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


def _path_of(raw, prefix=""):
    s = _unquote(raw.rstrip("\t"))
    if s == "/dev/null":
        return None
    return s[len(prefix):] if prefix and s.startswith(prefix) else s


def _git_paths(rest):
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


def diff_hashes(diff):
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


# ── Where each thread's code is now ──────────────────────────────────────────
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.M)
OUTDATED = ("outdated",)


def map_lines(hunks, start, end):
    """Lines <start>..<end> of a file, mapped through a diff's <hunks> ([(old start,
    old count, new start, new count)], in order, as `git diff -U0` gives them): the
    lines they are now, or None when the diff changed any of them (or added a line
    between them)."""
    shift = 0
    for old_start, old_count, new_start, new_count in hunks:
        if old_count == 0:  # lines added after line old_start
            if old_start >= end:
                break
            if old_start >= start:
                return None
            shift += new_count
            continue
        if old_start > end:
            break
        if old_start + old_count - 1 >= start:
            return None
        shift += new_count - old_count
    return start + shift, end + shift


def same_code(a, b):
    """The same lines, whatever the line endings."""
    def lines(s):
        return [line.rstrip("\r") for line in s.rstrip("\r\n").split("\n")]
    return lines(a) == lines(b)


class Code:
    """Where each thread's code is now, for the review of <branch> against <base>.

    When a thread is written, its anchor gets a snapshot: the whole file on that
    side of the view it was written in, in git's object database (in all changes,
    the file on disk for the new side, uncommitted too; the file where the branch
    left the base for the old side). Later, Code diffs the snapshot against that
    file now and maps the thread's lines through that diff: lines the diff doesn't
    touch follow their code, and a change to any of them makes the thread
    outdated. The anchor keeps its view, so a thread on the old side of HEAD~1
    follows its code there, even where the base never had that code. Nothing is found by its text, so the same code twice in a file
    can't move a thread to the wrong copy.
    """

    def __init__(self, cwd, base, branch):
        self.cwd = cwd
        self.base = base
        self.branch = branch
        self.top = _git(cwd, "rev-parse", "--show-toplevel") or cwd
        self._hashed = {}  # path: (its stat, its blob)
        self._diffs = {}  # (blob, blob): hunks

    def _run(self, *args):
        # Files in any encoding: only the line structure matters here
        r = subprocess.run(["git", "-C", self.top, *args], capture_output=True, text=True, errors="replace")
        return r.returncode, r.stdout

    def _blob_on_disk(self, file):
        """The file on disk, written to git's object database: its blob, or None
        when there is no such file. Raises ChangesError when git fails."""
        path = os.path.join(self.top, file)
        if not os.path.realpath(path).startswith(os.path.realpath(self.top) + os.sep):
            return None  # not a file of this repository
        try:
            st = os.stat(path)
        except FileNotFoundError:
            return None
        except OSError as e:
            raise ChangesError(str(e))
        key = (st.st_ino, st.st_size, st.st_mtime_ns)
        if self._hashed.get(path, (None,))[0] == key:
            return self._hashed[path][1]
        code, out = self._run("hash-object", "-w", "--", path)
        if code != 0:
            if not os.path.exists(path):
                return None
            raise ChangesError(f"could not read {file}")
        self._hashed[path] = (key, out.strip())
        return out.strip()

    def _branch_left_base(self):
        code, out = self._run("merge-base", self.base, "HEAD")
        if code != 0:
            raise ChangesError("no merge base")
        return out.strip()

    def _blob_at(self, commit, file):
        """The file's blob in <commit> ("" for the index)."""
        code, out = self._run("rev-parse", "--verify", "--quiet", f"{commit}:{file}")
        return out.strip() if code == 0 else None

    def _now(self, file, side, left=None):
        """The file's blob now on <side> (None when it isn't there)."""
        if side == "new":
            return self._blob_on_disk(file)
        return self._blob_at(left or self._branch_left_base(), file)

    def _in_view(self, file, side, view, left=None):
        """The file's blob on <side> of <view> (None when it isn't there): all
        changes compare where the branch left the base with the files on disk; a
        commit, that commit with them; staged, HEAD with the index; unstaged, the
        index with the files on disk."""
        if not view:
            return self._now(file, side, left)
        if side == "new":
            return self._blob_at("", file) if view == "staged" else self._blob_on_disk(file)
        return self._blob_at({"staged": "HEAD", "unstaged": ""}.get(view, view), file)

    def _lines(self, blob, start, end):
        code, out = self._run("cat-file", "blob", blob)
        if code != 0:
            return None
        lines = out.split("\n")
        if out.endswith("\n"):
            lines.pop()
        return "\n".join(lines[start - 1:end]) if end <= len(lines) else None

    def _hunks(self, a, b):
        if (a, b) not in self._diffs:
            code, out = self._run("diff", "--no-color", "--no-ext-diff", "-U0", a, b)
            if code != 0:
                if self._run("cat-file", "-e", a)[0] != 0:
                    return None  # the snapshot is gone (git gc): nothing to follow from
                raise ChangesError("git diff failed")
            self._diffs[(a, b)] = [(int(m[1]), 1 if m[2] is None else int(m[2]), int(m[3]),
                                    1 if m[4] is None else int(m[4])) for m in HUNK.finditer(out)]
        return self._diffs[(a, b)]

    def _on_branch(self):
        try:
            return review_branch(self.cwd, self.base) == self.branch
        except ChangesError:
            return False

    def snapshot(self, anchor, view=""):
        """The snapshot for a new anchor written in <view>, and the code on its lines
        in it: (blob, code), with None for what isn't there (no such file, or no such
        lines). Raises ChangesError when git fails."""
        blob = self._in_view(anchor["file"], anchor["side"], view)
        if blob is None:
            return None, None
        return blob, self._lines(blob, anchor["startLine"], anchor["endLine"])

    def follow(self, anchors):
        """Where the anchors ({thread id: anchor}) are now: {thread id: ("moved",
        start, end, snapshot) or OUTDATED}, for the ones that moved or became
        outdated. Nothing is followed while another branch is checked out, or
        when git fails: a thread only moves on a sure answer."""
        found = {}
        if not anchors or not self._on_branch():
            return found
        try:
            left = self._branch_left_base() if any(a["side"] == "old" for a in anchors.values()) else None
        except ChangesError:
            return found
        for tid, a in anchors.items():
            try:
                now = self._in_view(a["file"], a["side"], a.get("view") or "", left)
                if now == a.get("snapshot"):
                    continue
                if now is not None and not a.get("snapshot"):
                    # Written before snapshots existed: it follows from the file now,
                    # if its code is still on its lines
                    on_lines = self._lines(now, a["startLine"], a["endLine"])
                    found[tid] = ("moved", a["startLine"], a["endLine"], now) \
                        if on_lines is not None and a.get("code") is not None and same_code(a["code"], on_lines) \
                        else OUTDATED
                    continue
                hunks = None if now is None else self._hunks(a["snapshot"], now)
            except ChangesError:
                continue
            lines = None if hunks is None else map_lines(hunks, a["startLine"], a["endLine"])
            if lines is None:
                found[tid] = OUTDATED
            elif lines != (a["startLine"], a["endLine"]):
                found[tid] = ("moved", lines[0], lines[1], now)
        # A checkout while this ran: what it found may come from the other branch
        return found if not found or self._on_branch() else {}

    def place(self, threads, view):
        """Each thread's lines where its code is in <view>, in place: its snapshot
        diffed against the file in the view. A thread whose code isn't in the view
        (or changed in it) gets "inView": False and keeps its lines; an outdated
        thread keeps its lines, as it never sits next to code."""
        try:
            left = self._branch_left_base()
        except ChangesError:
            left = None
        for t in threads:
            a = t["anchor"]
            if not a or t["outdated"] or not a.get("snapshot"):
                continue
            try:
                there = self._in_view(a["file"], a["side"], view, left)
                hunks = [] if there == a["snapshot"] else None if there is None else self._hunks(a["snapshot"], there)
            except ChangesError:
                continue
            lines = None if hunks is None else map_lines(hunks, a["startLine"], a["endLine"])
            if lines is None:
                t["inView"] = False
            else:
                a["startLine"], a["endLine"] = lines
