---
name: write-review-path
description: Write a review path, `review-path.md`, for the current branch. Use when a card or branch is done and a reviewer needs a reading order, or when asked to "write the review path".
---

A **review path** is your reading order for a branch's changed files, with a few questions and answers per file, so the reviewer reads the change top-down with the context you have. You write one file, `review-path.md` at the worktree root. Nothing else: no tool reads your session, and you never run or call difftate.

Terms (see `GLOSSARY.md` if present): **stop** (a numbered file), **key stop** (★), **side file** (read with its stop, no number), **question** (a question with its answer; never "note"), **path section** (named text after the stops), **not on the path** (changed files the path leaves out).

## Steps

1. **Exclude the file.** The file must never be committed and never appear in its own review. Add one line to the exclude list shared by every worktree, if missing:

   ```sh
   ex=$(git rev-parse --git-path info/exclude)
   mkdir -p "$(dirname "$ex")"; touch "$ex"
   grep -qxF 'review-path.md' "$ex" || { [ -z "$(tail -c1 "$ex")" ] || echo >> "$ex"; echo 'review-path.md' >> "$ex"; }
   ```

   Done when `git check-ignore review-path.md` prints the name.

2. **Read the changeset**: the changes from the base to the files on disk. Base = `git symbolic-ref --short refs/remotes/origin/HEAD` (else `main`).

   ```sh
   git diff --stat "$(git merge-base <base> HEAD)"     # tracked changes, committed or not
   git ls-files --others --exclude-standard            # new files
   ```

   Read the diff of every file you need to understand. Read commit messages (`git log <base>..HEAD`) only where the diff leaves a file unclear.

3. **Use the ticket you already know** from this session: what it asked for, its acceptance criteria. Fetch nothing. With no ticket, write from the code alone and put the no-ticket line at the top (see the shape).

4. **Choose the order.** Write the path you would want to read:
   - Start where the change begins (the entry point or the contract), then follow it inward; each stop assumes only the stops before it.
   - A file that exists to serve another (its style, its test helpers, its types) is a side file under that stop. A part of a stop (a view's panel and its tips) is a nested stop.
   - Mark ★ on the few stops where the reviewer should slow down: a decision, a risk, the heart of the change.
   - Per stop, write one to three questions the reviewer asks on opening the file. The first asks what the user or the caller gets from it; the next ones, how it is built or why this way. Each answer is about intent, not location: name functions and components, never line numbers. Keep the path terse: it is a reading guide, and the diff, the tests and the commit bodies hold the rest.
   - Give a stop a spec only where the test is the clearest statement of what the file does, usually on a key stop. Most stops have none.
   - Put material that spans files (a state flow, an event list) in a path section, and point to it from a stop's answer by its name: `see "State flow"`.

5. **Account for every changed file.** Each changed file, including new files, appears exactly once, as a stop, a side file or in Skipped with a reason (`lockfile only`, `generated`, `rename with no change`). Never name a file that is not in the changeset.

6. **Write `review-path.md`** in the exact shape below, then check it against the rules. Done when every changed file is accounted for, and every heading matches one of the forms.

7. **Reply** with one line: the file's path and the number of stops. Write the file, then stop.

## The shape

The file is markdown a person can read as it is, and a program reads by these rules. Headings are the grammar: use the forms exactly.

| Part | Form | Rules |
|---|---|---|
| Frontmatter | `---`, `branch: <name>`, `createdAt: <UTC time>`, `---` | First lines of the file. `createdAt` is `YYYY-MM-DDTHH:MM:SSZ`; get it with `date -u +%Y-%m-%dT%H:%M:%SZ`. |
| Preamble | Any text before the first `##` | One or two sentences: the ticket and what the change does for the user. Branch history (rebases, commit hashes, review threads) stays in git. With no ticket, its first line is exactly `Written without a ticket: from the code only.` |
| Stop | ``## 2 `path/to/file.ts` ★`` | See below. |
| Nested stop | ``## 2.1 `path/to/file.ts` `` | Dotted number; the parent (`2`) must come first. Document order is reading order. |
| Spec | ``Spec: `path/to/file.test.ts` "test name"`` | A line directly under a stop's heading, before its first `###`. Optional; at most one per stop. |
| Question | `### Is the data good enough?` | Any `###` that is not a side file. The answer is the text under it, up to the next heading. |
| Side file | ``### Side file: `path/to/file.css` `` | Optional text under it: a short phrase saying what it is for (`the 10 tips`, `moved tests, plus the error case`). No number, no questions. |
| Path section | `## Section: State flow` | After the last stop. Free text, any `###` inside it is plain text. |
| Skipped | `## Skipped` | Last. One line each: ``- `path/to/file` — reason``. |

**Stop heading.** `## ` + number + space + the file in backticks + optionally ` ★`.
- The number is `1`, `2`, `3`… for stops in order, and `2.1`, `2.2`, `2.1.1`… for nested stops. No gaps.
- The file is a path from the repository root, forward slashes, as the changeset names it (a renamed file: its new path).
- No line ranges: a stop is the whole file. The path gives the reading order and the reasons, not where in the file the code is; line numbers go stale with every edit.
- ★ marks a key stop. It is the last thing on the line.

**One file, once.** A file is one stop, one side file, or one Skipped line; never two. Side files take no line ranges either.

**Questions** are plain text. A stop has one to three. Write each answer in one or two short lines, concrete, naming real things in the code; fragments are fine (`Card at 1.6s. Data limit 5s.`). A question earns its place when the reviewer would ask it while reading; a decision made along the way belongs in the commit body.

**Pointers.** A pointer from a stop to a path section is plain text: `see "State flow"`. Spell the name as in its `## Section:` heading.

## Example

A full file for a made-up branch, `feature/loading-flow`, in this shape:

````markdown
---
branch: feature/loading-flow
createdAt: 2026-11-22T06:10:00Z
---

PLAT-212: a loading flow (a quiz, then tips) while the trail downloads.

## 1 `src/loading/LoadingView.tsx` ★
Spec: `src/loading/LoadingView.test.tsx` "shows the quiz after two seconds"

### What does the user see while the trail downloads?
The spinner, then the quiz after 2s, then the tips if the quiz is skipped. See "State flow".

### Is the fetch cancelled when the user leaves?
Yes. The view calls the hook's `cancel` in its cleanup.

### Side file: `src/loading/loading.css`
Layout for the three states.

## 1.1 `src/loading/Quiz.tsx`

### When is there a quiz?
When the trail has 3 or more landmarks. Fewer: `buildQuiz` returns nothing, and the tips show.

## 1.2 `src/loading/Tips.tsx`

### Where do the tips come from?
`tips.json`, picked by the trail's difficulty. No network call.

### Side file: `src/loading/tips.json`
The tip texts.

## 2 `src/data/useTrailData.ts`

### How is the fetch built?
One request, retried twice, 500 ms apart. Returns `{ status, trail, cancel }`.

## 3 `src/analytics/loadingEvents.ts`

### What do we record?
One event per state change: the trail id and the time spent. No personal data.

## Section: State flow
The view starts on `spinner`. `ready` before two seconds goes straight to the trail. After two seconds it moves to `quiz`. `quiz` ends on a skip or on the last answer, and then shows `tips` until `ready`. `failed` shows the retry button from any state.

## Skipped
- `package-lock.json` — lockfile only
- `src/data/trailTypes.d.ts` — generated
````

Without a ticket, the line under the frontmatter reads `Written without a ticket: from the code only.` and the rest is unchanged.
