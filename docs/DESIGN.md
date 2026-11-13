# Comitra – Design Document

This document explains how the fragile parts of the original idea were redesigned and
describes the current architecture. It matches the code; if a decision changes, update
this document first.

## 1. Architecture

```
                ┌──────────── comitra/ui (PySide6) ────────────┐
                │ MainWindow · FilterPanel · ResultsModel       │
                │ DetailPanel · Dialogs · Workers (QThread)     │
                └───────────────┬───────────────────────────────┘
                                │ (only calls into core)
┌──────────────────────── comitra/core (no Qt dependency) ──────────────────────┐
│ scanner   → walks folders, finds repos (worktrees/submodules/bare)             │
│ gitcmd    → every git call: UTF-8, no prompts, no locks, timeouts              │
│ gitrepo   → refs, log parsing, rev-list, diff                                  │
│ fetcher   → optional safe `git fetch`                                          │
│ indexer   → ref-based incremental indexing, parallel workers, single writer    │
│ db        → SQLite schema, WAL, migrations (PRAGMA user_version)               │
│ query     → query language parser ⇄ Query object (round-trip)                  │
│ search    → Query → SQL, branch resolution, sorting, grouping                  │
│ textnorm  → case/accent normalization, highlighting                            │
│ stats, export, service                                                         │
└────────────────────────────────────────────────────────────────────────────────┘
comitra/cli.py → command-line interface on top of the same core
```

The core has no Qt dependency, so the CLI, the tests and the GUI share the same code.

## 2. Fragile points and their solutions

### 2.1 Branch membership (the most critical problem)

**Problem:** a `commit_branches(commit_id, branch_name)` table stores one row for
*every* branch that descends from a commit. 500k commits × 30 branches ≈ 15 million rows.
Worse: a fast-forward merge creates no new commits, but `main` now contains the feature
commits. `rev-list --all --not <old tips>` cannot see that change, so the table silently
goes stale.

**Solution:**

- Per-commit branch lists are **not stored**.
- The `refs` table stores each repository's tracked refs and their tip commits.
- Each commit stores the ref it was first discovered from (`first_ref`, via
  `git log --source`) for display.
- The `branch:` filter is resolved at query time: `git rev-list` runs from the tips of the
  matching refs and the result is cached under the key `(repo, tip commits)`. When a
  branch moves, the key changes and the cache entry is naturally replaced. About 1 s cold
  and milliseconds warm on a 100k-commit repository.
- If the repository folder is unavailable (e.g. an unplugged disk), `first_ref` gives an
  approximate answer and the user is warned.
- "Contained in" in the detail panel comes live from `git for-each-ref --contains`.

### 2.2 Incremental updates and lost commits

Updates are driven by refs, not dates:

1. Read the refs (local branches, remote branches, tags, detached HEAD). If their
   fingerprint is unchanged, the repository is skipped entirely.
2. `old` = stored tips that still exist, `new` = current tips.
3. New commits: `git log new --not old`. Every commit not seen before arrives, whatever
   its date.
4. Commits that became unreachable (force-push, rebase, deleted branch):
   `git rev-list old --not new` → marked `reachable = 0`, **not deleted**.
5. If a stored tip was removed by `git gc`, step 4 is impossible; a full reachability pass
   runs instead.
6. When a branch points at an unreachable commit again, it becomes `reachable = 1` again.

Unreachable commits are hidden in search by default and can be shown with
`unreachable:include|only` or from Settings. If "keep" is turned off, they are deleted.

### 2.3 Full-text search normalization

FTS5's `unicode61` tokenizer case-folds with plain Unicode rules, which are not
length-preserving for some letters (e.g. dotted capital I), and it does not match
"cafe" with "Café". Solution:

- Text is normalized with `textnorm.normalize` before it enters the index: lower case,
  all i variants → `i`, diacritics removed (é→e, ö→o, ß→s, ø→o…).
- The normalization is **length-preserving** (every character maps to exactly one
  character), so match positions found in the normalized text can be highlighted in the
  original text.
- Query terms go through the same function, so both sides always agree.
- Tokenizer: `unicode61 remove_diacritics 0 tokenchars '_'`. `snake_case` is one word;
  `JIRA-1234` is two words (searched as the phrase `"jira 1234"`).
- User input is never passed straight to FTS5. Every term becomes a quoted phrase, so
  characters like `"`, `*` or `:` cannot cause syntax errors.
- Exclusion (`-wip`) uses a separate `NOT IN` sub-query rather than FTS5's `NOT`
  operator, so a lone `-wip` works too.

### 2.4 Dates, hours and time zones

- Both the author date and the committer date are stored as UTC epoch seconds plus the
  commit's own time-zone offset (minutes). Rebasing changes the committer date; filters
  and sorting use the author date by default, configurable in Settings.
- Hour of day and weekday are computed and stored **in the commit's own time zone**
  (`author_hour`, `author_wday`…), so "commits between 22:00 and 06:00" follows the
  author's local clock.
- Date filters (today, last 7 days, ranges) use the **viewer's** local day.
- `after:` is inclusive, `before:` is exclusive. Ranges in the UI include both ends.

### 2.5 Repository identity

- A repository is recognized even after it moves: a newly found repository that matches
  a vanished one by root commit (and remote URL if needed) takes over its record, without
  re-indexing.
- Linked worktrees share refs with the main repository, so repositories are
  de-duplicated by the real path of their common git directory (`commondir`).
- Submodules (`.git` file → `.git/modules/x`) are indexed as separate repositories.
- Bare repositories (`HEAD` + `objects` + `refs`) are supported.
- A repository whose folder was deleted becomes `missing` and its commits stay
  searchable. Repositories outside the configured root folders become `inactive`. Both
  can be removed from the Repositories dialog.

### 2.6 Automatic discovery

With "Find repositories automatically" on (the default), the scan roots are the user's
home folder plus, on Windows, every fixed drive other than the system drive, in addition
to any folders the user adds. To keep a whole-home scan fast and free of noise:

- hidden folders (`.config`, `.cache`, `.oh-my-zsh` …) are skipped (configurable),
- app and media bundles (`*.app`, `*.photoslibrary` …) are skipped,
- system folders directly below a drive root (`Windows`, `Program Files`, `ProgramData` …)
  are skipped,
- the usual dependency and cache folders (`node_modules`, `venv`, `Library`, `AppData` …)
  are skipped, and the depth is limited (8 by default).

Only directory listings are read, never file contents, so even a large home folder is
scanned quickly.

### 2.7 Author identity

- `%aN/%aE` are used, so the repository's `.mailmap` is applied.
- `Co-authored-by:` trailers are parsed. The `author:` filter searches authors and
  co-authors together (name or e-mail, substring match).

### 2.8 Safe and portable git calls

`gitcmd` applies these to every call:

- `-c core.quotepath=off -c i18n.logOutputEncoding=UTF-8`, output decoded with
  `errors="replace"`. Non-ASCII file names and messages survive on Windows.
- `GIT_TERMINAL_PROMPT=0`, `credential.interactive=never`, `GCM_INTERACTIVE=never`.
  No call can hang waiting for a password.
- `GIT_OPTIONAL_LOCKS=0`, so Comitra never races the user's own git commands for
  `index.lock`.
- `CREATE_NO_WINDOW` on Windows, a separate process group elsewhere. On timeout the whole
  process tree is killed.
- Long inputs (ref lists, hashes) go through `--stdin` instead of the command line, so
  Windows' 32K command-line limit is never hit.
- Output is streamed. A one-million-commit log is never held in memory.
- If `git` is not on PATH, well-known install locations are checked; if it still cannot
  be found, a clear message is shown. A path can be set manually in Settings.
- In the PyInstaller Linux build, `LD_LIBRARY_PATH` is not passed on to git or to the
  terminal/editor that Comitra launches.

### 2.9 Fetch

Off by default. When enabled:

- `git fetch --all --no-prune --no-recurse-submodules --no-write-fetch-head`
  (overrides a user's `fetch.prune=true`).
- SSH runs with `BatchMode=yes` (unless the user configured their own `core.sshCommand`).
- Per-repository timeout, a limited number of parallel fetches, one retry on lock errors.
- Errors are classified as `auth / network / timeout / lock / error`. Indexing continues
  with local data and the problem is shown in the update report.

### 2.10 Concurrency

- Indexing runs in parallel with a `ThreadPoolExecutor` (git subprocesses don't hold the GIL).
- All writes go through a single `Writer` object, under a lock, in batched transactions
  of 2000 rows. SQLite runs in WAL mode.
- UI: indexing runs in a `QThread`, searching in another `QThread` with its own
  connection. "Newest request wins" discards stale search results. Diffs, containing
  branches, statistics and export are `QThreadPool` tasks. The UI never freezes.

### 2.11 Large result lists

A search returns the ordered ids of all matching commits (up to 2 million), so row counts
are exact. The table model loads rows in blocks of 200, only when they become visible
(LRU cache) – true virtual scrolling. Grouping works on the same id list.

### 2.12 Schema evolution

`PRAGMA user_version` holds the schema version. Every step appended to `db.MIGRATIONS` is
applied in order at start-up, inside a transaction. An older build opening a newer
schema fails with a clear error.

## 3. Database schema

| Table | Contents |
| --- | --- |
| `repos` | path, name, git dir, bare flag, root commit, remote URL, status, ref fingerprint, commit count |
| `refs` | tracked refs and their tip commits per repository |
| `commits` | hash, parents, author/committer, both dates + time zone + local hour/weekday, subject, message, `first_ref`, `reachable` |
| `coauthors` | `Co-authored-by` people |
| `paths`, `commit_files` | (optional) changed file paths, de-duplicated through a path dictionary |
| `commits_fts` | FTS5, normalized message; `rowid = commits.id` |
| `saved_searches`, `recent_searches` | saved and recent searches |

Diffs are not stored; the detail view fetches them from git on demand (2 MB limit).

## 4. Query language

`query.parse()` and `Query.to_string()` are inverses (verified by tests). The search box
and the filter panel share one `Query` object:

- The user types in the search box → parsed → the panel is updated (signals blocked).
- The user changes the panel → the `Query` is updated → the search box shows the
  canonical text.

Short aliases are accepted (`a:`, `r:`, `b:`, `d:`, `since:`, `until:`, `weekday:`…).
Invalid filters are not silently swallowed; they are shown as warnings.

## 5. Privacy and offline operation

- The app makes no network requests. The only exception is `git fetch`, which the user
  must explicitly enable and which only talks to the user's own git servers.
- No telemetry, no update check, no remote fonts or icons. All resources are bundled.

## 6. Portable mode

If a `comitra-portable.txt` file sits next to the program (portable packages include it),
or `--portable` / `COMITRA_HOME` is used, settings and the database live in a
`comitra-data` folder next to the program. Otherwise platformdirs picks the right
per-user folders for the operating system.

## 7. Measurements (development machine, Linux)

| Operation | Time |
| --- | --- |
| First index of a 100,000-commit repository | 4.6 s |
| Updating an unchanged repository | < 0.05 s |
| Full-text search (100k commits) | ~30 ms |
| Author + date + exclusion search | ~5 ms |
| `branch:` filter, cold cache | ~1.1 s |
| Database size (100k commits) | ~55 MB |
