"""The changeset: the review's changes in a view, for a viewer to show."""
from __future__ import annotations

from typing import Optional

from ..model import Changeset
from ..ports import ForReadingTheCode


def changeset(code: ForReadingTheCode, view: Optional[str] = "") -> Changeset:
    """The review's changeset in <view> ("" or None for all changes). Raises
    NotFound when <view> is no view (it names no commit), and CouldNotRead
    when the changeset can't be read."""
    return code.changeset(view or "")
