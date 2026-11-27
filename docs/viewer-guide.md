# The difftate viewer guide

This viewer guide tells a coding agent how to build a difftate viewer for any editor: the review API, difftate's capabilities, where to start, and how to check the work. `difftate --guide` prints it for the difftate that is installed; the same text is `docs/viewer-guide.md` in difftate's repository. The words in **bold** are difftate's own (its glossary): use them in the viewer too.

## 1. What a viewer is

A **viewer** is anything that talks to the **watcher**, the one difftate process on the machine, through its review API. In a viewer the **reviewer** reads a **review** (one branch against its **base**, like a pull request) and writes **comments**; the **coding agent** answers them. The **bundled viewers** (the browser and the Neovim viewer) use the same API as yours, and get nothing from difftate that your viewer can't. Your viewer belongs to the reviewer: their keys, their layout (threads inline or in a side panel), their editor. Nothing in this viewer guide fixes those.

## 2. Finding the watcher

**The difftate folder.** The watcher keeps its running files in the difftate folder of the home: `$DIFFTATE_HOME` when it is set and not empty, else `~/.difftate`. Read two files there for every request (a restarted watcher has a new port and a new token):

- `api.json`: `{"port": 51234, "pid": 4321}`. The API is `http://127.0.0.1:<port>`.
- `token`: the one token of the review API, on one line (strip the newline).

No `api.json`, or no answer on its port, means no watcher runs. Then show the reviewer: "No difftate is running: run `difftate` in a terminal".

**The token goes in a header**: `Authorization: Bearer <token>`, set by your HTTP client inside your viewer's process. Keep it out of every URL and every command line, where other processes and logs can read it. If your viewer shells out to `curl`, give the header in a config on stdin (`curl -K -`, then `header = "Authorization: Bearer <token>"`), as the Neovim viewer does. A request without the right token gets 401.

**Every request names its folder**: the query parameter `?folder=<path>`, on every method (GET, POST, PUT, PATCH), an absolute path in the checked-out folder (a repository or one of its worktrees) the editor has open, URL-encoded. A path below the folder's top names the same folder. The watcher answers about the review of the branch checked out there. File paths in answers and requests are relative to that folder's top (as in `git diff`). A request may also name a base, `&base=<branch>`; without one, the folder keeps its own base (the repository's default branch the first time). A request without a folder, or with a path in no checked-out folder of a git repository, gets 400. The one request that names no folder is `POST /api/stop`.

**A viewer never starts the watcher.** `difftate` starts it. The reviewer runs `difftate --open none` in the folder: it starts the watcher if none runs, adds the folder's review, and opens no bundled viewer. Then they open your viewer, which finds the watcher as above. (`DT_OPEN=none` makes that the default for plain `difftate`.)

**The first call**, and the one to repeat:

- `GET /api/review` sends nothing. Returns `{"id", "branch", "base", "waitingForRun", "checkedOut", "mode", "held", "folder", "warnings"}`. The first request that names a folder adds it to what the watcher serves.
  - `id` names the review. The watcher follows the checked-out branch: when `id` changes, the reviewer checked out another branch, and every list you show must be read again.
  - `branch` is the checked-out branch. With the base branch checked out, or a detached HEAD, the review is of the current commit: `branch` and `checkedOut` are its full id; shorten it for display.
  - `waitingForRun` is true while another branch is checked out than the review's; `checkedOut` names it. That lasts until a run that holds this review ends, or, with no run, until the watcher follows the checkout (within about a second). Show it in one line and keep polling: the review takes no new thread or viewed mark meanwhile (409).
  - `folder` is the checked-out folder's top. `mode` and `held` are the review mode (see 3.5).
  - `warnings`: `[{"id", "time", "text"}]` about the review (such as a `review-path.md` that can't be read). Show each `id` once.

**Rules for every call:**

- Bodies are JSON objects (`Content-Type: application/json`). Answers are JSON, except the export (text).
- Text that people and agents write is Markdown: every comment, reply and note `body`, and the review path's questions, answers, section text and side file text. Render it as untrusted: no raw HTML, no scripts, no links that run commands.
- An error is `{"error": "<message>"}` with 400 (a bad request), 401 (the token), 403 (a role that may not do this), 404 (no such thread, note or file), 409 (another branch is checked out) or 502 (git could not be read). Show the message to the reviewer as it is.
- The review API only grows: difftate updates add calls and fields, and never rename or remove one. Ignore fields you don't know, and keep working when a list has a value you don't know.
- Nothing is pushed to a viewer. Poll: the bundled viewers ask again every second or two (`GET /api/review`, `GET /api/threads`, and whatever else they show).
- `author` (in several bodies) is the role, and must be `"reviewer"`, the default: leave it out. A viewer always writes as the reviewer.

## 3. Capabilities

A **capability** is one thing difftate can do that a viewer may use. Each one below has what it is, its calls (method, path, what it sends, what it returns) and its rules. None is required: build the ones the reviewer wants.

### 3.1 Threads

**What it is.** A **thread** is a conversation about one **anchor**, or about the changeset as a whole (a **general thread**: `anchor` null). An anchor is a file, a **side** (`old`: before the change; `new`: after it), a line range, and the code on those lines when the thread was opened. When only the line numbers of its code change, the anchor moves with it. When the code itself changes, the thread is **outdated**: it stays, and keeps the lines and code it was written on. A thread holds **comments** (the reviewer's), **replies** (the coding agent's) and **notes** (difftate's own progress messages: a queued note or a progress note). Its **thread status** is `open`, `resolved` or `dismissed`; only a reviewer changes it. Its **thread state** says where an open thread stands in the loop: `held`, `waiting`, `queued`, `working`, `replied` or `failed` (null when not open).

A thread, as every call returns it:

```json
{"id": "8f1c…",
 "anchor": {"file": "app.py", "side": "new", "startLine": 2, "endLine": 2,
            "code": "    return f'hello {name}'", "snapshot": "<hash>", "view": "", "commit": "<sha>"},
 "outdated": false, "status": "open", "statusBy": null, "state": "replied",
 "comments": [{"id": "…", "author": "reviewer", "by": "Ada", "kind": "comment", "body": "Why an f-string?", "time": "2026-11-26T10:00:00+00:00"},
              {"id": "…", "author": "difftate", "by": null, "kind": "progress", "body": "✅ **Done** in 12s", "time": "…"},
              {"id": "…", "author": "agent", "by": null, "kind": "reply", "body": "It reads better.", "time": "…"}]}
```

`author` is `reviewer`, `agent` or `difftate`; `kind` is `comment`, `reply`, `queued` or `progress`; `by` is the **reviewer name** (null for a reply or a note). `statusBy` is the reviewer name of the last thread status change. In a view, `"inView": false` means the view's version of that file and side doesn't have the thread's code (most often: a thread on a deleted line); its lines are then those of the view it was written in, `anchor.view`. A thread without `inView` may still be on a file the view doesn't show, or on lines outside every hunk.

**Calls.**

- `GET /api/threads` sends nothing; optional `&status=open` (or `resolved`, `dismissed`) and `&view=<view>`. Returns a list of threads. With a view, each anchor's lines are where its code is in that view. Without `&view=`, the lines are those of all changes, not of the view viewers show (unlike the changeset and the review path): always pass the view you display.
- `POST /api/threads` sends `{"anchor": {"file", "side", "startLine", "endLine", "code", "version"}, "body", "view"}`. Returns the new thread. Send `anchor: null` for a general thread.
  - `startLine` and `endLine` are 1-based line numbers of that side, as the changeset's diff numbers them (1 ≤ start ≤ end). One line: both the same.
  - `code`: the exact text of those lines as the viewer showed them, joined with `\n`, with no newline at the end. A thread whose `code` isn't on those lines is outdated at once.
  - `version`: the changeset's `versions[file][side]` (see 3.3), a string to send back as it is; leave `version` out when that is null. With it, a file that changed since the viewer showed it still gets the thread on the right code.
  - `view`: the view the lines are in (default `""`, all changes).
  - Optional `reviewer`: a reviewer name (one line, at most 100 characters). Without one it is the repository's git `user.name`.
- `POST /api/threads/<id>/comments` sends `{"body"}` (optional `reviewer`). Returns the new comment: `{"id", "author", "by", "kind", "body", "time"}`.
- `PATCH /api/threads/<id>/status` sends `{"status": "open"|"resolved"|"dismissed"}` (optional `reviewer`). Returns `{"id", "status", "statusBy"}`.
- `PATCH /api/notes/<id>` sends `{"kind": "queued"|"progress", "body"}`. Returns the note. It is difftate's own call for its notes: a viewer shows notes and never edits them (anything that isn't a note gets 403).

**Rules.**

- Place a thread on its anchor's side and lines in the view you show. Place it on a line only when your view shows that file (it is in the changeset's `versions`) and that line; show every other thread, and each `inView: false` one, in a list.
- An outdated thread keeps the lines it was written on, and they may now hold other code. Show it with its own `code`, marked outdated, either only in the list (the browser viewer) or on its kept lines (the Neovim viewer, under "code when written"). Never show it as if it were about the code now on those lines.
- A viewer writes comments only (`kind` left out): the reviewer answers a thread, or a reply in it, by adding a comment. Replies come from the coding agent, notes from difftate.
- Show the thread state: it tells the reviewer whether the coding agent has the thread (`queued`, `working`), answered (`replied`) or failed (`failed`: its run ended with no reply; a new comment sends it again).
- Resolving or dismissing a thread is the reviewer's. Offer reopening (`open`) too.
- 409 while another branch is checked out: show the message, keep the reviewer's text.

### 3.2 Review path

**What it is.** The **review path** is the coding agent's reading order for the review's changed files: a tree of **stops**, each with **questions** and their answers, written by the coding agent in `review-path.md` at the folder's top. A stop is a numbered file (`"1"`, `"1.1"`, `"2"`: the numbers are the reading order), with optional line ranges. A **key stop** (★, `key: true`) is one where the reviewer should slow down. A **side file** is read together with its stop and has no number. A **skipped file** is a changed file the path names as not worth reading, with a reason. **Not on the path** are the changed files the path names nowhere, listed after the last stop. **Path sections** are named text after the stops that a stop's answers point to (`see`). A **spec** is a test a stop names.

**Calls.**

- `GET /api/review-path` sends nothing; optional `&view=<view>`. Returns `{"path": null}` when there is no `review-path.md`, or when it is out of shape (a heading out of shape, a file named twice, a file not in the changeset: then `GET /api/review` has a warning). A `review-path.md` the watcher can't open gets 502 with the reason, and the same warning. Text with no stops in it is a path with `stops: []`, every changed file not on the path. Else:

```json
{"path": {
  "stops": [{"number": "1", "file": "greet.py", "key": true, "viewed": false,
             "questions": [{"question": "What does this change?", "answer": "…"}],
             "ranges": [[4, 6]], "specs": [{"file": "test_greet.py", "name": "…"}], "see": ["The fallback"],
             "side_files": [{"file": "languages.py", "viewed": false, "ranges": [], "text": "…"}],
             "children": [{"number": "1.1", "file": "test_greet.py", "…": "…"}]}],
  "skipped": [{"file": "greetings.lock", "reason": "generated"}],
  "not_on_the_path": ["other.py"],
  "sections": [{"name": "The fallback", "text": "…"}]}}
```

**Rules.**

- Read it again when you poll: the coding agent may rewrite it at any time. Its file lists (`not_on_the_path`, and the files a view keeps) may lag a file that was just added by up to one second, while the changeset already has it: the next poll has it. No call order is needed. With `"path": null`, or a 502 from this call, show the changed files in the changeset's order and keep the rest of the poll.
- `ranges` are `[first, last]` new-side lines; `[]` is the whole file. `viewed` is the file's viewed mark (3.4).
- Show stops in their order and with their numbers, ★ on key stops, side files under their stop, then the skipped files with their reasons, then the files not on the path.
- In a view, the path is cut down to the view's files, numbers kept. Without `&view=` it is the view viewers show (3.3); `&view=` (empty) is all changes. Ask for the view you display.
- The viewer reads `review-path.md` through this call only, and never writes it: the coding agent does.

### 3.3 Views

**What it is.** A **view** is the part of the review's changes that the reviewer looks at: `""` (all changes), a commit such as `HEAD~2` (the commits after it, plus the uncommitted changes), `HEAD` (the uncommitted changes), `staged` or `unstaged`. Every view shows the same review: a thread written in any view belongs to it. The **changeset** is the changes from the base to the files on disk.

**Calls.**

- `GET /api/view` sends nothing. Returns `{"view"}`: the view viewers show.
- `PUT /api/view` sends `{"view"}`. Returns `{"view"}`. It changes the view that viewers show.
- `GET /api/changeset` sends nothing; optional `&view=<view>` (default: the view viewers show). Returns `{"view", "base", "commit", "diff", "versions", "waitingForRun", "checkedOut"}`: `diff` is a unified diff (`git diff`, new untracked files included); `commit` is where the branch left the base; `versions` is `{file: {"old", "new"}}`, the version of each side the diff shows (null for none), to send back as an anchor's `version`. A version is a git blob id in the folder's repository: `git cat-file blob <version>`, run in the folder, gives that side's whole file (for a side-by-side diff editor), in every view, new untracked files included. `versions` has one entry per file whose content the diff shows, in the diff's order: use its keys as the view's file list. A pure rename (no content change) has no entry today; it shows only as `rename from`/`rename to` lines in `diff`.

**Rules.**

- A view that isn't one gets 400, naming the views there are.
- No call lists the views. A view picker offers: all changes (`""`), `HEAD`, `staged`, `unstaged`, and `HEAD~N` for N from 1 up to the number of commits after `commit` (`git rev-list --count <commit>..HEAD` in the folder), where `commit` comes from `GET /api/changeset`.
- Pass the same `&view=` to threads, the changeset and the review path, so lines agree.
- To show your own view without changing the other viewers', pass `&view=` and leave `PUT /api/view` alone. `difftate <view>` sends `PUT /api/view`.

### 3.4 Viewed files

**What it is.** A **viewed file** is a file of the changeset that the reviewer marked as read. It stays viewed in every view, across reloads and commits, until the file's diff changes; then the mark is cleared.

**Calls.**

- `GET /api/viewed` sends nothing. Returns `{"files": [file]}`.
- `PUT /api/viewed` sends `{"file", "viewed": true|false}` (`viewed` defaults to true). Returns `{"files": [file]}`, the list after the change.

**Rules.**

- Read the list when you poll: a mark goes away on its own when the file changes.
- 404 for a file that isn't in the changeset; 409 while another branch is checked out.

### 3.5 Review mode: live, batched, submit

**What it is.** The **review mode** says how the reviewer's comments go to the coding agent. **Live** (every review starts live): each comment is dispatched as soon as it is written. **Batched**: each comment is held (thread state `held`) until the reviewer **submits** the review; then every held thread goes to the coding agent in one run. Changing a review from batched to live submits it too.

**Calls.**

- `GET /api/mode` sends nothing. Returns `{"mode": "live"|"batched", "held": [thread ids, oldest first]}`.
- `PUT /api/mode` sends `{"mode": "live"|"batched"}`. Returns `{"mode", "held", "submitted"}`: `submitted` are the ids a change to live submitted (`[]` for none).
- `POST /api/submit` sends `{}`. Returns `{"mode", "held", "submitted"}`: the held threads it submitted (`[]` when none was held; then no run starts).

**Rules.**

- **A viewer that starts threads in batched mode offers submit.** Without it, held threads never reach the coding agent.
- Show the mode and how many threads are held, so the reviewer knows comments are waiting.
- `GET /api/review` carries `mode` and `held` too: one poll is enough.

### 3.6 Done

**What it is.** **Done** says a reviewer has finished the review at one commit, whether they went through the code or skipped it. A new commit on the branch, or the reviewer undoing it, makes the review not done again. Only a reviewer marks it. It gates nothing.

**Calls.**

- `GET /api/done` sends nothing. Returns `{"done", "time", "commit", "lastMark", "head", "openThreads", "runsInFlight"}`: `time` and `commit` are the mark that made it Done (null when it isn't); `lastMark` is `{"kind": "done"|"undone"|"cleared", "time", "commit"}` or null; `head` is the commit the branch is at; `openThreads` and `runsInFlight` count the open threads, and those with a run queued or working.
- `PUT /api/done` sends `{"done": true|false}`. Returns the same as `GET /api/done`.

**Rules.**

- Read it again after a commit: `lastMark.kind` `"cleared"` means a new commit made the review not done.
- Show `openThreads` and `runsInFlight` beside the Done control, so the reviewer sees what is still open.
- 409 while another branch is checked out.

### 3.7 The coding agent that replies

**What it is.** The **coding agent** (such as Claude Code or OpenCode) answers threads in **runs**, and its answers come back as replies (`author: "agent"`, `kind: "reply"`), with difftate's **progress notes** on each thread while a run works. Which one replies comes from the machine's **agent list** (`agents.toml` in the difftate folder): the review's **agent override**, else the repository's agent, else the machine's default.

**Calls.**

- `GET /api/agent` sends nothing. Returns `{"agent", "source", "names"}`: the agent that replies, where that comes from (`"review"`: the override; `"repository"`; `"machine"`: the default) and the names on the agent list.
- `PUT /api/agent` sends `{"agent": "<a name on the list>"}`, or `{"agent": null}` to clear the override. Returns the same as `GET /api/agent`.

**Rules.**

- Replies and notes arrive in `GET /api/threads`: poll it. A progress note's `body` changes while its run works; show its latest text.
- A name that isn't on the list gets 400, naming the list. A run in flight keeps its agent: the next run uses the new one.

### 3.8 Export

**What it is.** An **export** is a copy of the review for an agent session that the reviewer starts: its commit messages, every thread in full with its thread status and thread state, which threads need an answer, and how to reply. It says nothing about what to do, and exporting changes no thread.

**Calls.**

- `GET /api/export` sends nothing; optional `&reply_folder=<folder>`. Returns the export as text (`text/plain`). With `reply_folder` (use `folder` from `GET /api/review`), the reply command in it names that folder.

**Rules.**

- Offer it as text to copy into an agent session (or to a file the reviewer picks). It needs no coding agent and writes nothing.

### Calls that are not a capability

- `POST /api/launch` sends `{}`. Returns `{"url"}`: a link that opens the browser viewer on the folder's review, with a single-use code. Your viewer can offer "open in the browser" with it.
- `POST /api/stop` sends `{}` and names no folder. Returns `{"stopping": true}`, then the watcher stops (`difftate stop` sends it). A viewer leaves it to the reviewer's terminal.

## 4. Start here

Threads, review mode with submit, and the review path make a useful first viewer. Build `GET /api/review`, then the changeset (`GET /api/changeset`, 3.3: the diff your viewer shows, and each anchor's `version`), then threads (list, place, start one on a line, comment, resolve), then the review mode and submit (3.5: the demo review is batched, and without submit its comments never reach the coding agent), then the review path. Check them against the demo review (section 5) before you add more.

When the reviewer named no capabilities, build the rest of section 3 after that, in its order. Leave one out only when the reviewer says so.

## 5. Checking your viewer

Run `difftate demo`. It makes a throwaway **demo review**, with one example of each capability, in a folder of its own in the temporary folder: a git repository, a difftate folder and a watcher of its own. The reviewer's own `~/.difftate` is never read or written. It prints the folder, the line that opens an editor on it with its difftate folder (`DIFFTATE_HOME=…`), and the line that removes it. Running it again makes a fresh one.

An editor that runs as one long-lived process (a JetBrains IDE, VS Code) gets `DIFFTATE_HOME` only from the process that started it: one opened from the Dock has none, and a second launch is handed to the running one. Quit it, then start it from a terminal with the variable set.

Open your editor in the demo's repository with that `DIFFTATE_HOME`, and check each capability:

- **Threads**: five threads.
  - On one line of `greet.py` (`word = GREETINGS.get(…)`), open, `held`.
  - On a range of lines in `languages.py` (`GREETINGS = {` to `}`), open, `held`.
  - In `test_greet.py`, with a reply from the coding agent: `replied`.
  - On `greet.py`'s import line, `resolved` (state null).
  - On `greet.py`'s `return` line, **outdated**, `held`: a later commit changed that code, so it keeps its own code and lines.
- **Review path**: stop 1, `greet.py` lines 4–6, a key stop (★), with the side file `languages.py` and a question that points to the path section "The fallback"; stop 1.1, `test_greet.py`; stop 2, `README.md`; the skipped file `greetings.lock` ("generated").
- **Views**: the branch `demo-languages` against `main`, two commits. All changes show five files; `HEAD~1` shows only the second commit's change to `greet.py`.
- **Viewed files**: `README.md` is viewed (and stop 2 says so).
- **Review mode**: batched. A new comment makes its thread `held`; submit sends the held threads.
- **Done**: not Done. Marking it shows `done: true` at the branch's commit.
- **The coding agent that replies**: the agent list names one agent, `demo`, whose command does nothing. A submitted run starts and ends with no reply, so its threads become `failed` with a progress note.
- **Export**: the export lists the five threads and the two commit messages.

What the demo doesn't show: no file is **not on the path** (the review path names every changed file), no general thread, no dismissed thread, no `waitingForRun`, no warning, and no agent override. Make them yourself if your viewer shows them: for `waitingForRun`, set the mode to live (`PUT /api/mode`), post a comment, and at once `git checkout main` in the demo repository; it lasts until the demo's run ends, about 2 seconds; a general thread or a dismissed one through the API; a new file in the demo's repository that the review path doesn't name; for a warning, name a file twice in the demo's `review-path.md`.

## 6. Working examples

Two clients of this API ship with difftate, in the folder `difftate` runs from (`bin/difftate` there; on GitHub, `TripathyM/difftate`):

- The Neovim viewer's API client, `lua/difftate/api.lua`: finding the watcher, the token through `curl -K -`, naming the folder. The rest of `lua/difftate/` places threads, the review path and the other capabilities in Neovim.
- The browser viewer, `lib/difftate/adapters/inbound/review_api/web/` (`app.js`, `diff.js`, `review_path.js`): every capability, polling every 1.5 s. It signs in with a cookie instead of the token; your viewer uses the token.
