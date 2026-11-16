"""The review's commit messages: the decisions behind the code, for a run's
prompt."""
from __future__ import annotations

from typing import List

from ..ports import ForReadingTheCode


def commit_messages(code: ForReadingTheCode) -> List[str]:
    """The message of each commit from the base to the review's branch, oldest
    first, whatever the view; empty when there are none. Raises CouldNotRead
    when they can't be read."""
    return code.commit_messages()
