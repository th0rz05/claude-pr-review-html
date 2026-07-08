# pr-review-html — install

A Claude Code skill that reviews a pull request and generates a self-contained,
interactive HTML report (CodeRabbit-style walkthrough: sidebar in reading order,
per-file Context / Review / Full diff tabs).

## Install (macOS / Linux)

The skill must live in `~/.claude/skills/pr-review-html/`. Copy the folder:

```bash
mkdir -p ~/.claude/skills
cp -R pr-review-html ~/.claude/skills/
```

Result:

```
~/.claude/skills/pr-review-html/
├── SKILL.md
└── generate_review_html.py
```

## Verify

Open a fresh Claude Code session and run `/pr-review-html <PR>`.
If it shows up in the skills list, it's installed.

## Requirements

- `python3` on PATH (the generator is pure Python, no external dependencies).
- `gh` CLI authenticated (to fetch the PR diff).
- The generated report has no external assets and works fully offline (system
  fonts, no CDN). It supports a light and a dark theme, toggled in the header.
