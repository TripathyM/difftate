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
side files, nesting and path sections are read by later tickets (#182, #183).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Collection, List, Optional, Tuple

# ## 1 `src/app.py:10-48,90-120` ★
STOP = re.compile(r"^## +(\d+(?:\.\d+)*) +`([^`]+)`(?: +★)? *$")
LINE_RANGES = re.compile(r":\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*$")
SIDE_FILE = re.compile(r"^### +Side file:")
SKIPPED = re.compile(r"^## +Skipped *$")
# - `package-lock.json` — lockfile only
SKIPPED_FILE = re.compile(r"^[-*] +`([^`]+)`(?: *[—–-]+ *(.*))?$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


@dataclass(frozen=True)
class Question:
    question: str
    answer: str


@dataclass(frozen=True)
class Stop:
    """A numbered file on the review path ("1", "2.1"), with its questions and
    the reviewer's viewed mark for the file."""
    number: str
    file: str
    questions: Tuple[Question, ...]
    viewed: bool = False


@dataclass(frozen=True)
class Skipped:
    """A changed file the coding agent left out on purpose, with its reason."""
    file: str
    reason: str


@dataclass(frozen=True)
class ReviewPath:
    stops: Tuple[Stop, ...]
    skipped: Tuple[Skipped, ...] = ()

    def with_viewed(self, viewed: Collection[str]) -> "ReviewPath":
        """The same path, each stop marked viewed when its file is one of <viewed>."""
        return replace(self, stops=tuple(replace(s, viewed=s.file in viewed) for s in self.stops))


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


def parse(text: str) -> ReviewPath:
    """The review path written in <text>."""
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

    for heading, line in _headings(text):
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
                stop = Stop(found[1], _file_of(found[2]), ())
        elif heading.startswith("### ") and stop is not None:
            end_question()
            if not SIDE_FILE.match(heading):
                question = heading[4:].strip()
        elif question is not None:
            answer.append(line)  # a deeper heading is part of the answer
    end_stop()
    return ReviewPath(tuple(stops), tuple(skipped))
