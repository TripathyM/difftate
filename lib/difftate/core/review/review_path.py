"""The review path (GLOSSARY.md, Review path): the coding agent's reading
order for a review's changed files, read out of the text of review-path.md.

The text has the shape the "write a review path" skill states
(skills/write-review-path/SKILL.md): frontmatter, a preamble, a `##` heading
per stop (number, the file in backticks with optional line ranges, optional
★), `###` questions with their answers under them, `### Side file:` entries,
`## Section:` path sections after the stops, and `## Skipped` last. Headings
are the grammar; a heading inside a fenced code block is text.

Pure: it reads text and knows no files and no git. It reads the stops in
document order with their questions, and the skipped files; ranges, ★, specs,
side files, key stops and nesting too; line ranges, specs and path sections are
read by a later ticket (#183).
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Collection, Dict, Iterator, List, Optional, Tuple

# ## 1 `src/app.py:10-48,90-120` ★
STOP = re.compile(r"^## +(\d+(?:\.\d+)*) +`([^`]+)`( +★)? *$")
LINE_RANGES = re.compile(r":\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*$")
SIDE_FILE = re.compile(r"^### +Side file:(?: *`([^`]+)`)?")
SKIPPED = re.compile(r"^## +Skipped *$")
SECTION = re.compile(r"^## +Section: *\S")
# - `package-lock.json` — lockfile only
SKIPPED_FILE = re.compile(r"^[-*] +`([^`]+)`(?: *[—–-]+ *(.*))?$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


class BadReviewPath(Exception):
    """The text can't be read as a review path. str(e) names the problem: the
    heading out of shape (with its line), or the file named wrongly."""


@dataclass(frozen=True)
class Question:
    question: str
    answer: str


@dataclass(frozen=True)
class SideFile:
    """A file read with its stop: no number, no questions."""
    file: str
    viewed: bool = False


@dataclass(frozen=True)
class Stop:
    """A numbered file on the review path ("1", "2.1"), with its questions, its
    side files and the stops under it, and the reviewer's viewed mark for the
    file. <key>: the agent marked it ★."""
    number: str
    file: str
    questions: Tuple[Question, ...]
    key: bool = False
    side_files: Tuple[SideFile, ...] = ()
    children: Tuple["Stop", ...] = ()
    viewed: bool = False

    def walk(self) -> Iterator["Stop"]:
        """This stop, then the stops under it, in reading order."""
        yield self
        for child in self.children:
            yield from child.walk()

    def with_viewed(self, viewed: Collection[str]) -> "Stop":
        return replace(self, viewed=self.file in viewed,
                       side_files=tuple(replace(f, viewed=f.file in viewed) for f in self.side_files),
                       children=tuple(c.with_viewed(viewed) for c in self.children))

    def files(self) -> Iterator[str]:
        """The files this stop and the stops under it name, side files included."""
        for stop in self.walk():
            yield stop.file
            for side in stop.side_files:
                yield side.file


@dataclass(frozen=True)
class Skipped:
    """A changed file the coding agent left out on purpose, with its reason."""
    file: str
    reason: str


@dataclass(frozen=True)
class ReviewPath:
    """<stops>: the top-level stops in reading order, the others under them.
    <not_on_the_path>: the changed files the path names nowhere (a side file or
    a skipped file is on the path), in the changeset's order."""
    stops: Tuple[Stop, ...]
    skipped: Tuple[Skipped, ...] = ()
    not_on_the_path: Tuple[str, ...] = ()

    def all_stops(self) -> Iterator[Stop]:
        """Every stop, children after their parent: the reading order."""
        for stop in self.stops:
            yield from stop.walk()

    def with_viewed(self, viewed: Collection[str]) -> "ReviewPath":
        """The same path, each stop and side file marked viewed when its file is one of <viewed>."""
        return replace(self, stops=tuple(s.with_viewed(viewed) for s in self.stops))

    def with_changed_files(self, changed: Collection[str]) -> "ReviewPath":
        """The same path, with the files of <changed> (the changeset's, in its
        order) it names nowhere as not on the path."""
        named = {f for s in self.stops for f in s.files()} | {s.file for s in self.skipped}
        return replace(self, not_on_the_path=tuple(f for f in changed if f not in named))


def _nest(flat: List[Stop]) -> Tuple[Stop, ...]:
    """The stops of <flat> (in document order) under their parents: 2.1 under
    2. A stop whose parent isn't there stands on its own."""
    known = {s.number for s in flat}
    under: Dict[str, List[Stop]] = defaultdict(list)
    roots: List[Stop] = []
    for stop in flat:
        parent = stop.number.rpartition(".")[0]
        (under[parent] if parent in known else roots).append(stop)

    def build(stop: Stop) -> Stop:
        return replace(stop, children=tuple(build(c) for c in under[stop.number]))

    return tuple(build(s) for s in roots)


def _file_of(target: str) -> str:
    """The file a stop heading names: its backticked text without line ranges."""
    return LINE_RANGES.sub("", target)


def _headings(text: str) -> List[Tuple[Optional[str], str]]:
    """Each line of <text> after the frontmatter: (the heading, or None for a
    line of text, a heading inside a code block included), the line."""
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        if end is not None:
            lines = lines[end + 1:]
    out: List[Tuple[Optional[str], str]] = []
    fence = ""  # the fence of the code block the line is in ("" outside one)
    for line in lines:
        found = FENCE.match(line)
        if found and not fence:
            fence = found[1]
        elif found and found[1][0] == fence[0] and len(found[1]) >= len(fence) and not line.strip()[len(found[1]):]:
            fence = ""  # as CommonMark: closed by the same character, at least as many, nothing after
            out.append((None, line))
            continue
        heading = line if not fence and re.match(r"^#{1,6} ", line) else None
        out.append((heading, line))
    return out


def check_files(path: ReviewPath, changed: Collection[str]) -> None:
    """Raises BadReviewPath when a file the path names (a stop, a side file or a
    skipped file) is not one of <changed>, the changeset's files."""
    for file in [f for s in path.stops for f in s.files()] + [s.file for s in path.skipped]:
        if file not in changed:
            raise BadReviewPath(f"`{file}` is named, but is not in the changeset")


def parse(text: str) -> ReviewPath:
    """The review path written in <text>. Raises BadReviewPath for a `##`
    heading that is no stop, `## Section:` or `## Skipped`, and for a file
    named by two stops."""
    stops: List[Stop] = []
    skipped: List[Skipped] = []
    stop: Optional[Stop] = None
    question: Optional[str] = None
    answer: List[str] = []
    in_skipped = False

    def end_question():
        nonlocal stop, question, answer
        if stop is not None and question is not None:
            stop = replace(stop, questions=stop.questions + (Question(question, "\n".join(answer).strip()),))
        question, answer = None, []

    def end_stop():
        nonlocal stop
        end_question()
        if stop is not None:
            stops.append(stop)
        stop = None

    headings = _headings(text)
    first_line = len(text.splitlines()) - len(headings) + 1  # the frontmatter is not in <headings>
    for at, (heading, line) in enumerate(headings, first_line):
        if heading is None:
            if question is not None:
                answer.append(line)
            elif in_skipped:
                found = SKIPPED_FILE.match(line.strip())
                if found:
                    skipped.append(Skipped(found[1], (found[2] or "").strip()))
            continue
        if heading.startswith("## ") or heading.startswith("# "):
            end_stop()
            in_skipped = bool(SKIPPED.match(heading))
            found = STOP.match(heading)
            if found:
                stop = Stop(found[1], _file_of(found[2]), (), key=bool(found[3]))
            elif heading.startswith("## ") and not in_skipped and not SECTION.match(heading):
                raise BadReviewPath(f'line {at}: "{heading.strip()}" is not a stop, a "## Section:" or "## Skipped"')
        elif heading.startswith("### ") and stop is not None:
            end_question()
            side = SIDE_FILE.match(heading)
            if side:
                if side[1]:
                    stop = replace(stop, side_files=stop.side_files + (SideFile(_file_of(side[1])),))
            else:
                question = heading[4:].strip()
        elif question is not None:
            answer.append(line)  # a deeper heading is part of the answer
    end_stop()
    seen = set()
    for stop in stops:
        for file in [stop.file] + [f.file for f in stop.side_files]:
            if file in seen:
                raise BadReviewPath(f"`{file}` is named twice")
            seen.add(file)
    return ReviewPath(_nest(stops), tuple(skipped))
