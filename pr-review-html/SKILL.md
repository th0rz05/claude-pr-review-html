---
name: pr-review-html
description: Review a pull request against your repo's standards and produce an interactive, self-contained HTML report (sidebar of files in reading order; each file has a "Context" tab explaining the change in plain language, a "Review" tab with severity-rated comments, and a "Full diff" tab showing every changed line). The review itself is deep and multi-lens — bugs, cross-file seams, tests, comments, silent failures, type design, conventions — where each finding is verified against the code and tagged confirmed or plausible, so only issues that hold up surface. Use when asked to review a PR and see both the findings and the full code changes in one place. The HTML is a temporary scratch artifact to delete after the comments are posted and the PR is merged.
allowed-tools: Bash, Read, Write, Grep, Glob
argument-hint: "[PR number or URL]"
---

# PR Review → interactive HTML

Reviews a PR against your repo's standards, then generates a single self-contained
HTML that presents the files as a **CodeRabbit-style walkthrough**: you read them
in *reading order* (the sequence that makes the PR make sense), not alphabetically,
and each file has three tabs in this order — **Context** (plain-language
explanation of what the file changes and why, shown first and by default),
**Review** (severity-rated comments) and **Full diff** (enhanced full diff with
old/new line numbers + word-level highlighting).

Two things must both be excellent: the **review** (deep, multi-lens, honest about
confidence — see step 3) and the **report** (the HTML output contract below).

## Reading order is the whole point

Do NOT list files alphabetically. Order them the way you'd explain the PR to a
teammate — source of truth first, then the thing that consumes it, then tests,
then build. The reader walks 1→N and understands the change by the time they
reach the end. This is encoded twice and must agree:
- `groups[]` order = the macro reading order (e.g. `★ Context` → `Consumers`
  → `Tests`).
- within a group, the **array order of `entries[]`** = the micro reading order.
The generator numbers files `1..N` in exactly that order and the sidebar,
Prev/Next buttons and `j`/`k` keys all walk it. The overview page renders the
same sequence as a clickable "Reading path" list — so give every entry a
one-line `walk` field saying *why it's read at this point*.

## Output contract (what the HTML must look like)

- Left **sidebar**: an "★ Overview" entry, then files grouped by theme in
  reading order. Each row shows its **step number**, filename, the `walk`
  one-liner, a severity badge and `+adds/-dels`. A live filter box (`/`) is on top.
- **Header**: title, subtitle, clickable **severity chips** summarising the
  finding counts (click a chip to hide/show that severity everywhere), and a
  stacked **severity meter** bar. A light/dark **theme toggle** sits top-right.
- **Overview page**: a stat grid (files, lines changed, one tile per severity),
  the goal, a before→after flow if a graph/pipeline changed, a one-line verdict,
  an optional info table, and the **Reading path** (numbered, clickable walkthrough).
- **Per-file page**: sticky header with Prev/Next; three tabs in order —
  `Context` (default: a plain-language explanation, in the chat language, of what
  this file changes and why, so the reader understands the change *before* seeing
  code), `Review` (severity-rated comments) and `Full diff` (two-gutter table with
  old+new line numbers, GitHub-style colours, and `<mark>` word-level highlights
  on replaced lines). Prev/Next repeat at the bottom.
- Every entry SHOULD carry a `context` field — narrate the change like you would
  to a teammate: what was there before, what it does now, how it fits the PR's
  story, any seam to watch. It is the landing tab, so it sets up the diff. If you
  omit it, the generator falls back to the one-line `walk`.
- A file that *should* have changed but did not (the seam of a bug), or a source
  file you include only for context, is still listed with a `note` (and no diff).
- Red banner at the top: temporary file, delete after posting + merge (dismissible).
- Keyboard: `j`/`k` or `←`/`→` next/prev file, `c`/`r`/`d` switch
  context/review/diff, `/` focus filter, `t` toggle theme. The shortcut keys are
  suppressed while a modifier is held, so `Cmd/Ctrl+C` copies selected text
  normally. Mention these to the user.
- Each Context and Review box has a `⧉ copy` button that copies the box text
  prefixed with `[Context]` / `[Review · SEVERITY]` and the file path, so a pasted
  snippet carries its own reference.
- The sidebar is resizable: drag the thin bar between the sidebar and the content
  (double-click resets). Width and theme persist in localStorage.
- `name` and `badge` per entry are optional: the generator derives `name` from the
  path basename and `badge` from the worst-severity comment (fallback `good`), so
  they never render as `undefined`.
- **Inline diff comments + jump**: a finding with a `line` anchor renders inline in
  the Full-diff tab at that line (GitHub-style), and its Review entry gets a
  "→ line N" button that jumps to and flashes it.
- **Seam map** (optional `seams`): the overview renders a panel of each changed
  symbol and its sites (producer/model/reader/tests); any not-updated side is
  flagged red and, if it's a file in the review, is clickable.
- **Blast radius** (optional `blast_radius`): the overview lists files that
  reference a changed symbol but are absent from the PR — candidate missed seams.
- **Review progress**: every finding has a "resolved" checkbox; the header shows a
  progress bar and the sidebar marks fully-resolved files. State persists in
  localStorage, so a reopened report remembers what you already cleared.
- **Diff niceties**: lightweight offline syntax highlighting and collapsible hunks
  (click a hunk header to fold it).

Severities: `block` (BLOCKER), `high`, `med`, `low` (NIT), `good` (OK), `new`.

## Workflow

### 1. Fetch the PR and confirm scope
```bash
PR=<number>            # from $ARGUMENTS (strip the URL if given)
gh pr view $PR --json number,title,author,headRefName,baseRefName,additions,deletions,changedFiles,body
gh pr diff $PR --name-only
gh pr diff $PR > /tmp/pr_${PR}.diff
```
Tell the user the file list and counts; proceed once confirmed.

### 1b. Isolate before you read or test — don't disturb the working tree
If your machine may have other tools, agents, or a dev server running against the
main checkout, do NOT `git checkout` the PR branch in the shared working tree — you
would flip the branch and clobber uncommitted work. Instead, check the PR branch
into its own throwaway worktree and read from there:
```bash
git fetch origin <headRefName>
git worktree add -f /tmp/pr_${PR}_wt origin/<headRefName>   # detached, isolated copy
cd /tmp/pr_${PR}_wt                                          # read from HERE
git worktree remove /tmp/pr_${PR}_wt --force                # when finished (run from the main repo)
```
A worktree isolates the *files*, but a local test run can still touch shared
resources (databases, containers, ports) that other processes use. So prefer
reading the PR's **own CI** — it is authoritative and touches nothing:
`gh pr checks $PR`. Only run the suite locally if you're sure nothing else is
using those resources, and do it inside the worktree.

### 2. Read the FULL files, not just the diff
A diff hides the seam where bugs live (an incomplete rename, a producer the diff
never touched, a duplicated sibling). Working inside the worktree from 1b:
- For every renamed field / moved symbol / new enum value, grep the WHOLE repo for
  the old and new names and confirm **producer, model, and reader all agree**. The
  classic miss: a field renamed in the model + reader + tests but not in the
  producer, so the value silently falls back to its default.
- For any new handler/component, find the sibling that already does the same job
  and compare — divergent duplicate logic is a finding.
- Verify claims in the PR description against the code (e.g. it says `password`,
  the code passes `new_password`).
- Check why CI did not catch a bug: isolated unit tests + mocked integration tests
  often bypass the exact seam that broke.

### 3. Review deeply — run every lens, then score every finding
This is the core of the skill. Do not do a single shallow pass. Review the change
through **each of the lenses below**, collect a raw list of candidate findings,
then **score and filter** them (3b) so only high-confidence issues reach the HTML.
Work in reading order (source of truth → consumers → tests) so context accrues.

**Lenses — apply each that is relevant to the files touched:**

1. **Correctness / bugs.** Logic errors, off-by-one, wrong operator, inverted
   condition, unhandled `null`/empty/edge input, incorrect async/await, resource
   leaks, race conditions, mutation of shared state, wrong default. Trace the data
   flow, don't pattern-match.
2. **Cross-file seams (the highest-value lens).** For every renamed/moved/added
   symbol, confirm **producer + model + reader + tests all agree**. A value that
   silently falls back to a default because one side wasn't updated is a BLOCKER
   that CI often misses. This is where full-file reading (step 2) pays off.
3. **Duplication & reuse.** Duplication is a serious smell. If new code
   re-implements an existing helper/sibling, flag it and point at the thing to
   reuse. Prefer reuse over rewrite; consistency with sibling modules over local
   cleverness.
4. **Silent failures.** `except: pass`, swallowed exceptions, a `catch` that logs
   nothing, a fallback that hides a real error, an optional return whose empty case
   is ignored downstream. Each one is a place a real failure goes invisible.
5. **Tests.** Does the test suite exercise the *actual behavior change*, not just a
   trivial branch? Missing coverage for the main change, tests that assert on
   mocks instead of behavior, tests that would still pass if the change were
   reverted — all findings. Note when CI's structure (isolated/mocked) bypasses the
   very seam the PR touches.
6. **Comments & docs.** Comments that now contradict the code (comment rot), stale
   docstrings, a changed function whose doc no longer matches its signature.
7. **Type design.** New/changed types: are invariants expressed in the type rather
   than defended at every call site? Overly-wide types (a bare string where an enum
   fits, an untyped map where a struct/dataclass fits), nullable fields that
   shouldn't be.
8. **Conventions (read them, don't work from memory).** See step 3c. Apply only the
   convention docs that match the files touched.
9. **Dead code / debris.** Leftover debug prints, commented-out blocks, unused
   imports/vars introduced by the change, TODOs left in shipped code.

**3b. Verify each candidate, then decide — don't score.**
Numeric confidence scores are false precision: an LLM can't reliably tell a "78"
from an "83", so a "keep everything ≥ 80" rule is theatre. What actually matters is
whether you *verified* the finding. For each candidate:

1. **Try to disprove it.** Trace it in the real code — open the producer, the
   sibling, the caller. Many candidates die here; that is the point of the pass.
2. **Require evidence.** Keep it only if you can point at concrete, checkable proof —
   the line, the trace, the site that wasn't updated. A finding you can't ground in
   something checkable is a guess: drop it.
3. **Tag what survives, binary.** LLMs *are* well-calibrated on a two-way split, so
   label each surviving finding:
   - `confirmed` — you verified it in the code; the evidence is in the body.
   - `plausible` — it looks real but you could not fully verify it (missing context,
     runtime-dependent). Keep only if it's genuinely worth the reader's time, and
     mark it so — never dress a guess as a certainty.
4. **Severity is impact, not confidence.** `block`/`high`/`med`/`low` rate how much
   it hurts *if real*; the separate `confirmed`/`plausible` tag rates how sure you
   are. A confirmed nit is still `low`; a plausible data-loss bug is still `high`.

If you flagged something then disproved it while reading, keep the trail as a `good`
comment rather than deleting it — it shows the seam was checked. Keep applying the
false-positive list below throughout: it is a rule, not a score, and it is the real
filter that keeps the report trustworthy.

**Do NOT flag (false positives):**
- Pre-existing issues, or issues on lines the PR did not modify.
- Something that looks like a bug but isn't once you trace it.
- Pedantic nitpicks a senior engineer wouldn't raise.
- Anything a linter/typechecker/compiler catches (missing imports, type errors,
  formatting, unused-after-CI). Assume CI runs these — do NOT build or typecheck.
- Generic "add more tests / more docs / more security" unless a convention doc
  requires it for this change.
- A convention-doc issue that the code explicitly silences (e.g. a lint-ignore).
- Changes in behavior that are clearly intentional and part of the PR's purpose.

### 3c. Apply the project's standards (read them, do not work from memory)
- The repo's **`CLAUDE.md`** — the root one, plus any `CLAUDE.md` in the directories
  the PR touched. Treat these as the primary source of project rules.
- Any contributor/convention docs the repo ships (e.g. `CONTRIBUTING.md`, a
  `docs/`/`conventions/` folder, an `.editorconfig`, lint configs). Apply only the
  ones relevant to the files changed.
- **Prompt hygiene** (only when the PR changes LLM prompts or tool schemas): LLMs
  produce tokens, they do not "read/see/think" — flag anthropomorphic verbs;
  chain-of-thought / reasoning fields MUST precede the label/classification field;
  prefer a concrete example over an abstract description.
- When you cite a convention in a finding, quote the specific line — a finding that
  says "violates conventions" without the quote is not actionable.

### 4. Author the review JSON
Write `/tmp/pr_${PR}_review.json` following the schema in
`generate_review_html.py` (top docstring). Rules:
- **Order entries by reading order, not alphabetically** (see the section above).
  `groups[]` is the macro order; the array order of `entries[]` is the micro
  order within each group. Give every entry a one-line `walk` explaining why it
  is read at that point.
- Give every entry a `context` field: a short plain-language paragraph (HTML,
  in the chat language) explaining what this file changes and why — what was
  there before, what it does now, how it fits the PR's story. This is the default
  tab and it must stand on its own: someone reading only the Context tabs 1→N
  should understand the whole PR without opening a single diff. Keep it narrative,
  not a restatement of the diff. `<p>`, `<b>`, `<code>`, `<ul>` allowed.
- One `entries` item per file worth discussing; `comments` is a list of
  `[severity, "Headline", "HTML body"]` (+ optional 4th element = GitHub draft).
  Bodies may use `<code>`, `<b>`, `<br>`. Make the body explain *why* it's a
  problem and *what to do*, not just *what* — that's what makes the report worth
  more than GitHub's inline UI.
- **Anchor findings to a line** whenever you can: append the NEW-file line number as
  a trailing element of the comment array (after the optional GitHub draft). The
  finding then renders inline in the diff and gets a "→ line N" jump — the single
  biggest reading win, so do it for every finding that points at a concrete line.
- Tag each finding's **confidence** (from step 3b) by appending the string
  `"confirmed"` or `"plausible"` as a trailing element of the comment array
  (order-independent with the GitHub draft and the line number). Omit it for `good`
  notes. Use `confirmed` only when you actually verified it in the code; use
  `plausible` for anything you could not fully check — the report renders a
  `plausible` marker so the reader knows it's unverified.
- Populate **`seams`** from the cross-file-seam lens (step 3, lens 2): one entry per
  changed symbol, each site `{role, path, ok}` with `ok:false` for a side that was
  NOT updated. This surfaces the highest-value class of bug at a glance.
- Populate **`blast_radius`** from a repo-wide grep of each changed symbol: files
  that reference it but are not in the PR — candidate missed seams.
- Set **`pr.repo`** (`owner/repo`, from the PR URL) and **`pr.ref`** (the head SHA —
  `gh pr view $PR --json headRefOid`). This turns every file path into a link: seam
  sites and blast-radius files that aren't in the diff open on GitHub (deep-linked to
  the line when you give one), so the reviewer clicks straight to the evidence
  instead of grepping by hand. Give seam sites a `line` and blast items a `{path,line}`
  wherever you know the line.
- Include a file absent from the diff when it is the cause of a bug OR the source
  of truth needed to understand a seam (give it a `note`; no diff needed — the
  generator handles it). This is how you show context files first.
- `overview_html` is free HTML; reuse the `.intro`, `.why`, `.warn`, `.flow`,
  `.node`, `table.info` classes the template already styles. Do NOT hand-author a
  walkthrough list or a stat grid in `overview_html` — the generator builds both
  (the stat grid from the finding counts, the walkthrough from the `walk` fields).
- `groups` lists the sidebar group order; every entry's `group` must be in it.
- Be honest about confidence and severity. If you flagged something then proved it
  wrong while reading, say so in a `good` comment rather than deleting the trail.

### 5. Generate and open
```bash
python3 ~/.claude/skills/pr-review-html/generate_review_html.py \
  --diff /tmp/pr_${PR}.diff --review /tmp/pr_${PR}_review.json --out /tmp/pr_${PR}_review.html
open /tmp/pr_${PR}_review.html      # macOS; use xdg-open on Linux
```
(The generator lives next to this SKILL.md in `~/.claude/skills/pr-review-html/`.)
Clean up the worktree and intermediate JSON/diff. Remind the user the HTML is
temporary: delete it after the comments are posted and the PR is merged.

### 6. (Optional) Post the comments
Only if the user asks. Use `gh api repos/<owner>/<repo>/pulls/$PR/reviews` with
inline comments anchored to the right path+line; BLOCKER as `REQUEST_CHANGES`,
the rest as suggestions. Follow the user's git conventions.

**Always write GitHub-facing text in English**, even when the chat is in another
language — PR comments are read by the whole team. Keep it plain prose, no em
dashes, no machine-report tone. (The HTML scratch file can stay in the chat
language since it is for the user only.)
