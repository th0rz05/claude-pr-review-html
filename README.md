# pr-review-html

A [Claude Code](https://claude.com/claude-code) skill that reviews a pull request
**deeply** and turns the result into a single, self-contained **interactive HTML
report** — a CodeRabbit-style walkthrough you read instead of squinting at
GitHub's review tab.

The review is the point: it reads the *full files* (not just the diff), runs the
change through a set of focused lenses (bugs, cross-file seams, tests, silent
failures, type design, conventions…), and **verifies each finding before showing
it** — tagged *confirmed* or *plausible* so a guess is never dressed up as a
certainty. The report just makes that easy to read.

![Overview](docs/screenshot-overview.png)

---

## Why

GitHub's review UI scatters a PR across tabs and shows you an alphabetical file
list with no story. This skill instead gives you **one HTML file** that:

- orders files in **reading order** — source of truth → consumers → tests — so the
  PR explains itself as you walk 1 → N;
- gives every file a plain-language **Context** tab *before* any code, so you
  understand the change before reading the diff;
- puts **severity-rated findings** and the **full diff** (with word-level
  highlighting) one click away;
- is **self-contained and offline** — one `.html`, no server, no CDN, no tracking.
  Open it, read it, delete it.

## Features

- **Deep, multi-lens review that verifies before it reports** — every finding is
  tagged *confirmed* or *plausible* (an unverified guess is marked, never shown as
  fact), so you get fewer false positives than a one-shot pass.
- **Reading-order walkthrough** with a numbered sidebar, Prev/Next, and a clickable
  reading path on the overview.
- **File-status badges:** every file is tagged **added / deleted / renamed** straight
  from the diff — shown in the sidebar and file header, independent of review
  severity, so a deleted file never reads as "new".
- **Three tabs per file:** Context (plain-language), Review (severity-rated
  comments), Full diff (two-gutter, GitHub-style colours, `<mark>` word highlights).
- **Inline diff comments + jump:** findings anchor to a line, render inline in the
  diff GitHub-style, and get a "→ line N" jump from the Review tab.
- **Seam map — an active negative-space check:** for each changed symbol, Claude
  opens every place it lives (producer / model / reader / tests) and judges whether
  it should have changed; any side that *wasn't* updated is flagged **red**. The
  highest-value class of bug, surfaced at a glance.
- **Blast radius with a verdict:** files that reference a changed symbol but aren't in
  the PR — each one opened and given Claude's verdict inline (*checked — unaffected*
  / *MISSED — still reads the old shape*). A real missed change is promoted to a
  first-class finding, not just a red chip.
- **Click straight to the evidence — contained:** seam sites and blast-radius files
  that aren't in the PR open their code in an in-report **peek panel** (the snippet
  ships with the report — no network, still one self-contained file). Files that
  *are* in the PR jump to their page in the report. Set `pr.repo` + `pr.ref` and
  anything without a snippet falls back to a GitHub deep-link.
- **Review progress:** tick findings off as you resolve them; a header progress bar
  and per-file checkmarks track it, persisted across reopens.
- **Overview dashboard:** stat grid, before→after flow, one-line verdict.
- **Light & dark themes**, toggled in the header (remembered across visits).
- **Syntax-highlighted, collapsible diffs**, keyboard-driven (`j`/`k` navigate,
  `c`/`r`/`d` tabs, `/` filter, `t` theme), copy-ready comments with GitHub drafts.
- **Zero dependencies:** pure-Python generator, system fonts, one offline file.

|         Review tab (jump + resolve)          |         Full diff (inline comments)          |
| :------------------------------------------: | :------------------------------------------: |
| ![Review](docs/screenshot-review.png)        | ![Diff](docs/screenshot-diff.png)            |
|            Seam map & blast radius            |     Peek a referenced file — in-report       |
| ![Seam map](docs/screenshot-seam-map.png)    | ![Peek](docs/screenshot-peek.png)            |

## Install

The skill lives in `~/.claude/skills/pr-review-html/`.

**From the release zip:**
```bash
unzip pr-review-html.zip
mkdir -p ~/.claude/skills
cp -R pr-review-html ~/.claude/skills/
```

**Or from this repo:**
```bash
git clone https://github.com/th0rz05/claude-pr-review-html.git
mkdir -p ~/.claude/skills
cp -R claude-pr-review-html/pr-review-html ~/.claude/skills/
```

Then open a fresh Claude Code session — `/pr-review-html` should appear in the
skills list.

### Requirements

- [Claude Code](https://claude.com/claude-code)
- `python3` on your PATH (the generator has no external dependencies)
- `gh` CLI, authenticated (`gh auth login`) — used to fetch the PR diff

## Usage

In Claude Code:

```
/pr-review-html 123
/pr-review-html https://github.com/owner/repo/pull/123
```

Claude fetches the PR, reviews it against your repo's standards (it reads your
`CLAUDE.md` and any convention docs), writes a review, generates the HTML, and
opens it. Ask it to post the findings as inline PR comments if you want.

## How it works

```
gh pr diff ──▶ read full files ──▶ multi-lens review ──▶ verify & tag ──▶ review.json
                                                                               │
                                                        generate_review_html.py ▼
                                                                          report.html
```

The skill's methodology lives in [`pr-review-html/SKILL.md`](pr-review-html/SKILL.md);
the generator and its JSON schema are documented at the top of
[`pr-review-html/generate_review_html.py`](pr-review-html/generate_review_html.py).
You can also run the generator directly:

```bash
python3 pr-review-html/generate_review_html.py \
  --diff pr.diff --review review.json --out report.html
```

## Example

Open [`examples/example-report.html`](examples/example-report.html) in a browser to
see a full report for a sample PR — a boards-sharing migration that deletes one file,
adds two, and leaves a stale reference outside the diff (the red seam). It's fully
reproducible from the committed inputs:

```bash
python3 pr-review-html/generate_review_html.py \
  --diff examples/demo.diff --review examples/demo-review.json \
  --out examples/example-report.html
```

## Notes

- The generated HTML is a **temporary scratch artifact** — a banner reminds you to
  delete it after the review is done.
- The report is for *reading* a review comfortably; posting to GitHub is a separate,
  optional step.

## License

[MIT](LICENSE) © Tiago Barbosa ([@th0rz05](https://github.com/th0rz05))

> Built as a Claude Code skill. Not affiliated with GitHub or CodeRabbit.
