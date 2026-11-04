---
status: accepted
---

# A review on the base branch itself lasts one commit

A review is identified by its branch and its base, like a pull request, so on a branch it survives every commit. On the base branch itself (`main` against `origin/main`), or on a detached HEAD, there is no branch to identify it with, so the current commit stands in for the branch. After a commit there, the watcher moves to a new, empty review (it follows the checked-out branch, and the commit was the branch). The earlier review's threads stay in its folder and in the review history; they just aren't shown. We accept this because changes are made on a branch and reach the base through a pull request (or merge request), as they would on GitHub, where a pull request from `main` into `main` can't exist.

## Considered options

- **`main` against `origin/main` as one review.** It survives commits, but it never ends: threads on work pushed long ago would stay in it.
- **`main` plus its merge base with `origin/main`.** It survives local commits and starts again after a push or a pull, which plays the part of a pull request's merge. It's the better fit if working straight on the base branch is ever common, but nobody works that way now, so it isn't worth its code and tests.

## Consequences

- Reviewing work committed straight to the base branch means one review per commit. Work on a branch to keep threads across commits.
- If committing straight to the base branch becomes a real workflow, the merge-base option is the one to build. Only `changes.review_branch` and the review id change.
