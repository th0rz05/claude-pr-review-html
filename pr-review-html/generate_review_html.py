#!/usr/bin/env python3
"""Generate a self-contained, interactive PR-review HTML report.

Combines a structured review (overview + per-file comments) with the real git
diff. Files are shown in **reading order** (a CodeRabbit-style walkthrough), not
alphabetically: you read them top-to-bottom in the sequence that makes the PR
make sense. Each file has three tabs, in this order: "Context" (a plain-language
explanation of what this file changes and why, shown FIRST and by default),
"Review" (the severity-rated comments) and "Full diff" (every changed line, with
old/new line numbers and word-level highlighting).
Output is one standalone .html file — no external assets, works offline.

Usage:
    python3 generate_review_html.py --diff <pr.diff> --review <review.json> --out <out.html>

review.json schema:
{
  "pr":   {"number": 114281, "title": "...", "subtitle": "Jane Doe · 5 files",
            "counts": "1 HIGH, 2 MEDIUM, 1 NIT"},
  "overview_html": "<div class='intro'>...</div>",   # free HTML for the ★ Overview page
  "groups": ["★ Context", "Consumers", ...],         # sidebar group order == reading order
  "entries": [                                        # WITHIN a group, array order == reading order
    {
      "path": "src/graph.py",             # full repo path; matched against the diff
      "name": "graph.py",                # OPTIONAL sidebar label; defaults to the path basename
      "group": "Consumers",              # must be one of "groups"
      "badge": "block|high|med|low|good|new",   # OPTIONAL; defaults to the worst severity among comments (or "good")
      "walk": "one line: why you read this file at this point in the walkthrough",
      "context": "HTML: plain-language explanation of what this file changes and why, read BEFORE the diff. This is the default tab. Narrate the change like you would to a teammate: what was there before, what it does now, how it fits the PR's story. May use <p>,<code>,<b>,<ul>. Falls back to `walk` if omitted.",
      "note": "optional highlighted banner shown above the tabs (or null)",
      "comments": [
        ["block", "Headline", "HTML body explaining the problem in depth"],
        ["high",  "Headline", "HTML body", "Optional GitHub draft (plain text) shown in a copy box"]
      ]
    }
  ]
}

Reading order = groups[] order, then entries[] array order within each group.
Author the entries in the order a reviewer should read them; the sidebar numbers
them 1..N and Prev/Next + the j/k keys walk that same order.

A file listed in entries but absent from the diff (e.g. the source of truth that
explains a seam, or a file that SHOULD have changed but did not) renders its note
instead of a diff. A file present in the diff but not in entries is appended
automatically at the end with an empty review.
"""
import argparse
import html
import json
import re

SEV = {"block": "b-block", "high": "b-high", "med": "b-med",
       "low": "b-low", "good": "b-good", "new": "b-new"}
SEVL = {"block": "BLOCKER", "high": "HIGH", "med": "MEDIUM",
        "low": "NIT", "good": "OK", "new": "NEW"}

WORD_RE = re.compile(r"\s+|\w+|[^\w\s]", re.UNICODE)


def split_diff(raw):
    """Return {path: diff_text} keyed by the b/ path of each file in a git diff."""
    out = {}
    for chunk in re.split(r"(?m)^(?=diff --git )", raw):
        if not chunk.strip():
            continue
        m = re.search(r"^diff --git a/(\S+) b/(\S+)", chunk)
        if not m:
            continue
        out[m.group(2)] = chunk.rstrip("\n")
    return out


def _counts(diff):
    """(additions, deletions) for a file diff, ignoring the +++/--- headers."""
    add = dele = 0
    for ln in diff.split("\n"):
        if ln.startswith("+") and not ln.startswith("+++"):
            add += 1
        elif ln.startswith("-") and not ln.startswith("---"):
            dele += 1
    return add, dele


def _word_diff(old_body, new_body):
    """Char/word-level highlight of a removed line vs the added line that replaces it.

    Returns (old_html, new_html) with the differing middle wrapped in <mark>.
    Common leading/trailing tokens stay unwrapped so the eye jumps to the change.
    """
    o = WORD_RE.findall(old_body)
    n = WORD_RE.findall(new_body)
    i = 0
    while i < len(o) and i < len(n) and o[i] == n[i]:
        i += 1
    j = 0
    while j < len(o) - i and j < len(n) - i and o[-1 - j] == n[-1 - j]:
        j += 1
    o_mid, n_mid = o[i:len(o) - j], n[i:len(n) - j]

    def render(pre, mid, suf, kind):
        h = html.escape("".join(pre))
        if mid:
            h += f'<mark class="wd wd-{kind}">' + html.escape("".join(mid)) + "</mark>"
        return h + html.escape("".join(suf))

    return (render(o[:i], o_mid, o[len(o) - j:], "del"),
            render(n[:i], n_mid, n[len(n) - j:], "add"))


def _row(old_ln, new_ln, sign, code_html, cls):
    o = "" if old_ln is None else str(old_ln)
    n = "" if new_ln is None else str(new_ln)
    return (f'<tr class="{cls}"><td class="ln">{o}</td><td class="ln">{n}</td>'
            f'<td class="sg">{sign}</td><td class="cd">{code_html}</td></tr>')


def diff_to_html(diff):
    """Render a file diff as a two-gutter table with word-level highlights.

    Skips the git noise header (diff --git / index / --- / +++); each page is one
    file already. Deleted lines immediately followed by added lines are paired and
    word-diffed so intra-line edits pop.
    """
    if not diff:
        return '<div class="nocomment">This file is not part of the PR diff.</div>'

    old_ln = new_ln = 0
    rows = []
    del_buf, add_buf = [], []  # (line_number, body) pending pairing

    def flush():
        # Pair deletions with additions index-wise; word-diff the overlap.
        paired = min(len(del_buf), len(add_buf))
        for k in range(paired):
            oln, obody = del_buf[k]
            nln, nbody = add_buf[k]
            oh, nh = _word_diff(obody, nbody)
            rows.append(_row(oln, None, "-", oh, "del"))
            rows.append(_row(None, nln, "+", nh, "add"))
        for oln, obody in del_buf[paired:]:
            rows.append(_row(oln, None, "-", html.escape(obody), "del"))
        for nln, nbody in add_buf[paired:]:
            rows.append(_row(None, nln, "+", html.escape(nbody), "add"))
        del_buf.clear()
        add_buf.clear()

    for line in diff.split("\n"):
        if line.startswith(("diff --git", "index ", "--- ", "+++ ",
                            "rename ", "similarity ", "new file", "deleted file",
                            "old mode", "new mode")):
            continue
        if line.startswith("@@"):
            flush()
            m = re.search(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            if m:
                old_ln, new_ln = int(m.group(1)), int(m.group(2))
            rows.append(f'<tr class="hunk"><td class="ln"></td><td class="ln"></td>'
                        f'<td class="sg"></td><td class="cd">{html.escape(line)}</td></tr>')
            continue
        if line.startswith("-"):
            del_buf.append((old_ln, line[1:]))
            old_ln += 1
        elif line.startswith("+"):
            add_buf.append((new_ln, line[1:]))
            new_ln += 1
        else:
            flush()
            body = line[1:] if line.startswith(" ") else line
            rows.append(_row(old_ln, new_ln, "", html.escape(body), "ctx"))
            old_ln += 1
            new_ln += 1
    flush()
    return '<table class="diff"><tbody>' + "".join(rows) + "</tbody></table>"


def build(diff_path, review_path, out_path):
    raw = open(diff_path, encoding="utf-8").read()
    diffs = split_diff(raw)
    review = json.load(open(review_path, encoding="utf-8"))

    entries = review["entries"]
    seen = {e["path"] for e in entries}
    for path in diffs:
        if path not in seen:
            entries.append({
                "path": path, "name": path.split("/")[-1],
                "group": review.get("default_group", "Other changes"),
                "badge": "good", "note": "Change not commented in the review.",
                "comments": [],
            })

    # Reading order = groups[] order, then entry array order within each group.
    groups = review["groups"]
    order = {g: i for i, g in enumerate(groups)}
    entries.sort(key=lambda e: order.get(e.get("group"), len(groups)))

    sev_rank = {"block": 0, "high": 1, "med": 2, "low": 3, "new": 4, "good": 5}
    for seq, e in enumerate(entries, 1):
        d = diffs.get(e["path"])
        e["seq"] = seq
        e["diffHtml"] = diff_to_html(d)
        e["comments"] = e.get("comments", [])
        e["walk"] = e.get("walk", "")
        e["context"] = e.get("context") or (f"<p>{e['walk']}</p>" if e.get("walk") else "")
        # Derive display fields when the review omits them, so they never render "undefined".
        if not e.get("name"):
            e["name"] = e["path"].split("/")[-1]
        # Badge: derive from the worst comment severity when missing OR when the
        # author typed a severity we don't recognise (so a typo never shows blank).
        if e.get("badge") not in SEV:
            sevs = [c[0] for c in e["comments"] if c and c[0] in SEV]
            e["badge"] = min(sevs, key=lambda s: sev_rank.get(s, 99)) if sevs else "good"
        if d:
            a, r = _counts(d)
            e["add"], e["del"] = a, r
        else:
            e["add"], e["del"] = 0, 0

    pr = review["pr"]
    overview = review.get("overview_html", "<p>(no overview)</p>")
    payload = json.dumps({"entries": entries, "groups": groups,
                          "overview": overview}, ensure_ascii=False)

    out = _TEMPLATE.replace("__PR_TITLE__", html.escape(pr.get("title", "")))
    out = out.replace("__PR_SUB__", html.escape(pr.get("subtitle", "")))
    out = out.replace("__PR_COUNTS__", html.escape(pr.get("counts", "")))
    out = out.replace("__OUT_PATH__", html.escape(out_path))
    out = out.replace("__PAYLOAD__", payload)
    open(out_path, "w", encoding="utf-8").write(out)
    print(f"written {out_path} ({len(out)} bytes, {len(entries)} files)")


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>PR Review</title>
<style>
/* ============================================================================
   PR Review — a refined, precision-instrument reading surface for code review.
   Dark-first, with a genuine light theme. Signature accent: teal.
   ========================================================================== */
:root{
  --font-ui:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,'Helvetica Neue',sans-serif;
  --font-mono:ui-monospace,'SF Mono','JetBrains Mono','Cascadia Code',Menlo,Consolas,monospace;
  --radius:12px;--radius-sm:8px;--radius-xs:6px;
  --ease:cubic-bezier(.2,.7,.2,1);
}
/* ---- dark (default) ---- */
:root,:root[data-theme="dark"]{
  color-scheme:dark;
  --bg:#0a0c11;--bg-glow:#0e1420;--bg-elev:#0e1118;--panel:#12161f;--panel-2:#171c27;
  --line:#20262f;--line-2:#2b3341;--line-3:#3a4453;
  --fg:#e7ebf2;--fg-2:#9aa4b4;--fg-3:#67717f;
  --accent:#2dd4bf;--accent-2:#5eead4;--accent-soft:#2dd4bf1f;--accent-line:#2dd4bf59;
  --link:#7fd6ff;
  --add-bg:#0e2a1b;--add-fg:#5fd38a;--add-ln:#0c2417;
  --del-bg:#2e161b;--del-fg:#ff9a95;--del-ln:#28141a;
  --shadow:0 1px 0 #ffffff08,0 12px 34px -18px #00000099;
  --grain:.025;
  --code-bg:#1a2130;--code-fg:#a9d8ff;
}
/* ---- light ---- */
:root[data-theme="light"]{
  color-scheme:light;
  --bg:#f4f6f9;--bg-glow:#e8eef7;--bg-elev:#ffffff;--panel:#ffffff;--panel-2:#f1f4f8;
  --line:#e4e8ee;--line-2:#d6dce4;--line-3:#c3cbd6;
  --fg:#131820;--fg-2:#57616f;--fg-3:#8994a2;
  --accent:#0d9488;--accent-2:#0f766e;--accent-soft:#0d948814;--accent-line:#0d94884d;
  --link:#0369a1;
  --add-bg:#e6f8ee;--add-fg:#1a7f45;--add-ln:#d6f2e2;
  --del-bg:#fdecec;--del-fg:#c0362f;--del-ln:#f8dcdc;
  --shadow:0 1px 0 #ffffff,0 10px 30px -20px #1b2a4a33;
  --grain:.015;
  --code-bg:#eef2f7;--code-fg:#0b5c8a;
}
*{box-sizing:border-box}
html,body{height:100%}
body{
  margin:0;font-family:var(--font-ui);background:var(--bg);color:var(--fg);
  font-size:14px;line-height:1.55;-webkit-font-smoothing:antialiased;
  text-rendering:optimizeLegibility;font-feature-settings:"cv02","cv03","ss01";
}
/* atmospheric backdrop: a soft top glow + faint grain so it never reads flat */
body::before{content:"";position:fixed;inset:0;z-index:-2;pointer-events:none;
  background:radial-gradient(120% 60% at 78% -8%,var(--bg-glow),transparent 60%),
             radial-gradient(90% 50% at 0% 0%,var(--accent-soft),transparent 55%);}
body::after{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;opacity:var(--grain);
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");}
::selection{background:var(--accent-soft);color:var(--fg)}
::-webkit-scrollbar{width:11px;height:11px}
::-webkit-scrollbar-thumb{background:var(--line-2);border:3px solid transparent;background-clip:padding-box;border-radius:99px}
::-webkit-scrollbar-thumb:hover{background:var(--line-3);border:3px solid transparent;background-clip:padding-box}
a{color:var(--link);text-decoration:none}a:hover{text-decoration:underline}

/* ---- temporary-file banner ---- */
.banner{display:flex;align-items:center;justify-content:center;gap:9px;
  background:linear-gradient(90deg,transparent,var(--del-bg),transparent);
  color:var(--del-fg);padding:7px 20px;font-size:.75em;letter-spacing:.02em;
  border-bottom:1px solid var(--line);text-align:center}
.banner code{background:none;color:inherit;font-weight:600}
.banner .x{margin-left:8px;cursor:pointer;opacity:.6;border:1px solid currentColor;border-radius:5px;
  padding:0 6px;line-height:1.4}.banner .x:hover{opacity:1}

/* ---- header ---- */
header{position:relative;padding:20px 30px 0;border-bottom:1px solid var(--line);
  background:linear-gradient(180deg,var(--bg-elev),transparent)}
.head-top{display:flex;align-items:flex-start;justify-content:space-between;gap:20px}
.eyebrow{font-family:var(--font-mono);font-size:.66em;letter-spacing:.28em;font-weight:600;
  color:var(--accent);text-transform:uppercase;margin-bottom:8px;display:flex;align-items:center;gap:9px}
.eyebrow::before{content:"";width:20px;height:1px;background:var(--accent-line)}
header h1{margin:0;font-size:1.5em;font-weight:680;letter-spacing:-.02em;color:var(--fg);line-height:1.2}
header .meta{color:var(--fg-2);font-size:.85em;margin-top:7px}
header .meta b{color:var(--del-fg);font-weight:600}
.tools{display:flex;gap:8px;flex-shrink:0}
.iconbtn{display:inline-flex;align-items:center;gap:7px;cursor:pointer;user-select:none;
  border:1px solid var(--line-2);background:var(--panel);color:var(--fg-2);
  border-radius:99px;padding:6px 13px;font-size:.76em;font-weight:500;transition:all .16s var(--ease)}
.iconbtn:hover{border-color:var(--accent-line);color:var(--fg);transform:translateY(-1px)}
.iconbtn svg{width:14px;height:14px}

/* severity chips + meter */
.chips{display:flex;gap:7px;margin-top:15px;flex-wrap:wrap;align-items:center}
.chip{display:inline-flex;align-items:center;gap:7px;padding:4px 11px 4px 9px;border-radius:99px;
  font-size:.72em;font-weight:600;border:1px solid var(--line-2);background:var(--panel);
  cursor:pointer;transition:all .16s var(--ease)}
.chip:hover{border-color:var(--line-3);transform:translateY(-1px)}
.chip.off{opacity:.4}
.chip .dot{width:8px;height:8px;border-radius:50%;box-shadow:0 0 0 3px color-mix(in srgb,currentColor 18%,transparent)}
.chip .n{font-variant-numeric:tabular-nums;color:var(--fg)}
.chip .l{color:var(--fg-3);font-weight:600;letter-spacing:.02em}
.meter{display:flex;height:5px;border-radius:99px;overflow:hidden;margin:16px 0 0;background:var(--line);gap:2px}
.meter span{display:block;transition:width .5s var(--ease)}

/* ---- layout ---- */
.layout{display:flex;height:calc(100vh - 176px)}
.sidebar{width:340px;flex-shrink:0;border-right:1px solid var(--line);display:flex;
  flex-direction:column;background:linear-gradient(180deg,var(--bg-elev),var(--bg))}
.resizer{width:7px;flex-shrink:0;cursor:col-resize;background:transparent;transition:background .14s;
  position:relative}
.resizer::after{content:"";position:absolute;inset:0 3px;border-radius:99px}
.resizer:hover::after,.resizer.dragging::after{background:var(--accent)}
body.resizing{cursor:col-resize;user-select:none}

.search{padding:14px 14px 9px}
.search-wrap{position:relative}
.search svg{position:absolute;left:12px;top:50%;transform:translateY(-50%);width:14px;height:14px;color:var(--fg-3)}
.search input{width:100%;background:var(--panel);border:1px solid var(--line-2);border-radius:var(--radius-sm);
  color:var(--fg);padding:9px 12px 9px 34px;font-size:.82em;outline:none;transition:all .16s var(--ease);font-family:var(--font-ui)}
.search input::placeholder{color:var(--fg-3)}
.search input:focus{border-color:var(--accent-line);box-shadow:0 0 0 3px var(--accent-soft);background:var(--bg-elev)}

.filelist{overflow-y:auto;padding:2px 0 20px;flex:1}
.grouphdr{color:var(--fg-3);font-size:.64em;font-weight:700;text-transform:uppercase;letter-spacing:.13em;
  padding:16px 20px 6px;font-family:var(--font-mono)}
.file-item{position:relative;padding:9px 14px 9px 13px;cursor:pointer;font-size:.8em;
  border-left:2px solid transparent;display:flex;align-items:center;gap:10px;transition:background .1s}
.file-item::before{content:"";position:absolute;left:0;top:6px;bottom:6px;width:2px;border-radius:99px;background:transparent;transition:background .16s}
.file-item:hover{background:var(--panel)}
.file-item.active{background:var(--panel-2)}
.file-item.active::before{background:var(--accent)}
.file-item .seq{flex-shrink:0;width:22px;height:22px;border-radius:var(--radius-xs);background:var(--panel-2);
  color:var(--fg-3);font-size:.82em;font-weight:700;display:flex;align-items:center;justify-content:center;
  font-variant-numeric:tabular-nums;font-family:var(--font-mono);border:1px solid var(--line);transition:all .16s}
.file-item:hover .seq{border-color:var(--line-2)}
.file-item.active .seq{background:var(--accent-soft);color:var(--accent-2);border-color:var(--accent-line)}
.file-item .fmeta{min-width:0;flex:1}
.file-item .fname{font-family:var(--font-mono);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--fg);font-size:.98em}
.file-item.active .fname{color:var(--accent-2)}
.file-item .fwalk{color:var(--fg-3);font-size:.85em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:2px}
.file-item .fright{flex-shrink:0;display:flex;flex-direction:column;align-items:flex-end;gap:4px}
.counts{font-family:var(--font-mono);font-size:.82em;font-weight:600;white-space:nowrap;letter-spacing:-.01em}
.counts .a{color:var(--add-fg)}.counts .d{color:var(--del-fg)}
.ov-item .fname{font-weight:650;font-family:var(--font-ui)}
.ov-item .seq{color:var(--accent-2)}

/* ---- content ---- */
.content{flex:1;overflow-y:auto;padding:26px 34px 70px;scroll-behavior:smooth}
.content-inner{max-width:1080px}

/* severity badges */
.badge{display:inline-flex;align-items:center;padding:2px 7px;border-radius:5px;font-size:.62em;
  font-weight:800;letter-spacing:.04em;flex-shrink:0;vertical-align:middle;font-family:var(--font-mono);
  border:1px solid transparent}
.b-block{background:color-mix(in srgb,var(--sev-block) 15%,transparent);color:var(--sev-block);border-color:color-mix(in srgb,var(--sev-block) 40%,transparent)}
.b-high{background:color-mix(in srgb,var(--sev-high) 15%,transparent);color:var(--sev-high);border-color:color-mix(in srgb,var(--sev-high) 40%,transparent)}
.b-med{background:color-mix(in srgb,var(--sev-med) 15%,transparent);color:var(--sev-med);border-color:color-mix(in srgb,var(--sev-med) 40%,transparent)}
.b-low{background:color-mix(in srgb,var(--sev-low) 15%,transparent);color:var(--sev-low);border-color:color-mix(in srgb,var(--sev-low) 40%,transparent)}
.b-good{background:color-mix(in srgb,var(--sev-good) 15%,transparent);color:var(--sev-good);border-color:color-mix(in srgb,var(--sev-good) 40%,transparent)}
.b-new{background:color-mix(in srgb,var(--sev-new) 15%,transparent);color:var(--sev-new);border-color:color-mix(in srgb,var(--sev-new) 40%,transparent)}
:root{--sev-block:#ff5c72;--sev-high:#ff9147;--sev-med:#f2c14e;--sev-low:#6cb8ff;--sev-good:#54d38a;--sev-new:#b79bff}
:root[data-theme="light"]{--sev-block:#dc2f45;--sev-high:#d9730a;--sev-med:#b7860b;--sev-low:#2b7fd4;--sev-good:#1a9a54;--sev-new:#7c5cd6}

/* per-file sticky head */
.filehead{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;position:sticky;top:-26px;
  background:linear-gradient(180deg,var(--bg) 62%,transparent);padding:8px 0 14px;margin:-8px 0 0;z-index:6;
  backdrop-filter:blur(2px)}
h2.filetitle{color:var(--fg);font-family:var(--font-mono);font-size:1.08em;word-break:break-all;margin:0;
  font-weight:650;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.sub{color:var(--fg-3);font-size:.78em;font-family:var(--font-mono);margin:5px 0 16px;word-break:break-all}
.sub .dotsep{opacity:.5;margin:0 6px}
.navbtns{display:flex;gap:8px;flex-shrink:0}
.navbtn{display:inline-flex;align-items:center;gap:6px;padding:7px 13px;border:1px solid var(--line-2);
  border-radius:var(--radius-sm);cursor:pointer;font-size:.78em;background:var(--panel);color:var(--fg-2);
  white-space:nowrap;user-select:none;transition:all .16s var(--ease)}
.navbtn:hover{border-color:var(--accent-line);color:var(--accent-2);transform:translateY(-1px)}
.navbtn[disabled]{opacity:.32;pointer-events:none}

/* tabs */
.tabs{display:inline-flex;gap:4px;margin-bottom:18px;padding:4px;background:var(--panel);
  border:1px solid var(--line);border-radius:99px}
.tab{padding:6px 16px;border-radius:99px;cursor:pointer;font-size:.82em;color:var(--fg-2);font-weight:550;
  transition:all .16s var(--ease);border:1px solid transparent;display:inline-flex;align-items:center;gap:7px}
.tab:hover{color:var(--fg)}
.tab.active{background:var(--accent-soft);color:var(--accent-2);border-color:var(--accent-line)}
.tab .tcount{font-size:.86em;font-family:var(--font-mono);opacity:.8}

.note{background:color-mix(in srgb,var(--sev-med) 10%,transparent);border:1px solid color-mix(in srgb,var(--sev-med) 32%,transparent);
  border-left:3px solid var(--sev-med);border-radius:var(--radius-sm);padding:10px 15px;margin-bottom:18px;
  font-size:.86em;color:var(--fg)}

/* review comments */
.comment{position:relative;border-radius:var(--radius);padding:14px 18px;margin:12px 0;background:var(--panel);
  border:1px solid var(--line);box-shadow:var(--shadow);overflow:hidden}
.comment::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px}
.comment.c-block::before{background:var(--sev-block)}.comment.c-high::before{background:var(--sev-high)}
.comment.c-med::before{background:var(--sev-med)}.comment.c-low::before{background:var(--sev-low)}
.comment.c-good::before{background:var(--sev-good)}.comment.c-new::before{background:var(--sev-new)}
.copybtn{position:absolute;top:11px;right:12px;cursor:pointer;color:var(--fg-3);font-size:.7em;
  border:1px solid var(--line-2);border-radius:var(--radius-xs);padding:3px 9px;background:var(--bg-elev);
  opacity:.6;transition:all .16s var(--ease);display:inline-flex;align-items:center;gap:5px}
.copybtn:hover{opacity:1;border-color:var(--accent-line);color:var(--accent-2)}
.copybtn.ok{color:var(--sev-good);border-color:color-mix(in srgb,var(--sev-good) 40%,transparent);opacity:1}
.comment .chead{font-weight:680;font-size:.9em;margin-bottom:7px;display:flex;align-items:center;gap:10px;padding-right:70px;color:var(--fg)}
.comment .cbody{font-size:.9em;line-height:1.64;color:var(--fg-2)}
.comment .cbody b{color:var(--fg);font-weight:650}
.comment .cbody code{white-space:pre-wrap}

.gh{margin-top:13px;background:var(--bg-elev);border:1px solid var(--line-2);border-radius:var(--radius-sm);padding:10px 13px}
.gh .ghlabel{color:var(--fg-3);font-size:.64em;text-transform:uppercase;letter-spacing:.1em;margin-bottom:7px;
  display:flex;align-items:center;justify-content:space-between;font-family:var(--font-mono)}
.gh .ghtext{font-family:var(--font-mono);font-size:.82em;line-height:1.6;color:var(--fg);white-space:pre-wrap}
.gh .copy{cursor:pointer;color:var(--accent-2);font-size:.95em;border:1px solid var(--line-2);border-radius:5px;
  padding:1px 8px;background:var(--panel);transition:border-color .16s}
.gh .copy:hover{border-color:var(--accent-line)}
.nocomment{color:var(--fg-3);font-style:italic;font-size:.9em;padding:10px 0}

/* context tab */
.ctx-explain{position:relative;font-size:.93em;line-height:1.72;max-width:900px;color:var(--fg-2);
  background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--accent);
  border-radius:var(--radius);padding:17px 22px;box-shadow:var(--shadow)}
.ctx-explain p{margin:0 0 12px}.ctx-explain p:last-child{margin-bottom:0}
.ctx-explain b{color:var(--fg);font-weight:650}.ctx-explain ul{margin:9px 0;padding-left:20px}.ctx-explain li{margin:4px 0}
.ctx-explain h4{color:var(--fg);font-size:.98em;margin:18px 0 8px}

code{background:var(--code-bg);padding:1.5px 5px;border-radius:5px;font-size:.88em;color:var(--code-fg);font-family:var(--font-mono)}

/* overview page */
.ov-hero{margin-bottom:6px}
.ov-hero h2{font-size:1.9em;font-weight:720;letter-spacing:-.025em;margin:0 0 6px;color:var(--fg);
  display:flex;align-items:center;gap:12px}
.ov-hero .star{color:var(--accent);font-size:.8em}
.stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px;margin:22px 0 6px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:14px 16px;
  box-shadow:var(--shadow);position:relative;overflow:hidden;transition:transform .16s var(--ease),border-color .16s}
.stat:hover{transform:translateY(-2px);border-color:var(--line-2)}
.stat .big{font-size:1.9em;font-weight:720;font-variant-numeric:tabular-nums;letter-spacing:-.02em;line-height:1}
.stat .lab{color:var(--fg-3);font-size:.68em;text-transform:uppercase;letter-spacing:.1em;margin-top:7px;font-family:var(--font-mono)}
.stat .tick{position:absolute;top:14px;right:14px;width:8px;height:8px;border-radius:50%}
.intro{font-size:.94em;line-height:1.72;max-width:920px;color:var(--fg-2)}
.intro h3{color:var(--fg);font-size:1.05em;margin:26px 0 9px;letter-spacing:-.01em}
.intro b{color:var(--fg);font-weight:650}
.intro .why{background:color-mix(in srgb,var(--sev-good) 9%,transparent);border:1px solid color-mix(in srgb,var(--sev-good) 26%,transparent);
  border-left:3px solid var(--sev-good);padding:11px 16px;border-radius:var(--radius-sm);margin:16px 0;color:var(--fg)}
.intro .warn{background:color-mix(in srgb,var(--sev-med) 9%,transparent);border:1px solid color-mix(in srgb,var(--sev-med) 26%,transparent);
  border-left:3px solid var(--sev-med);padding:11px 16px;border-radius:var(--radius-sm);margin:16px 0;color:var(--fg)}

/* reading-path walkthrough */
.walk{list-style:none;padding:0;margin:16px 0;max-width:920px}
.walk li{display:flex;gap:13px;padding:12px 14px;border:1px solid var(--line);border-radius:var(--radius);
  margin-bottom:9px;cursor:pointer;background:var(--panel);align-items:flex-start;
  transition:all .16s var(--ease);box-shadow:var(--shadow)}
.walk li:hover{border-color:var(--accent-line);transform:translateX(3px)}
.walk .seq{flex-shrink:0;width:24px;height:24px;border-radius:var(--radius-xs);background:var(--panel-2);
  color:var(--fg-3);font-size:.78em;font-weight:700;display:flex;align-items:center;justify-content:center;
  font-family:var(--font-mono);border:1px solid var(--line-2)}
.walk .wtxt{min-width:0;flex:1}
.walk .wname{font-family:var(--font-mono);font-size:.88em;color:var(--accent-2)}
.walk .wdesc{color:var(--fg-2);font-size:.85em;margin-top:3px}

.flow{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin:14px 0}
.flow .node{background:var(--panel-2);border:1px solid var(--line-2);padding:6px 11px;border-radius:var(--radius-xs);font-size:.76em;font-family:var(--font-mono)}
.flow .node-new{background:color-mix(in srgb,var(--sev-good) 12%,transparent);border-color:color-mix(in srgb,var(--sev-good) 40%,transparent);color:var(--add-fg)}
.flow .arrow{color:var(--fg-3)}
table.info{border-collapse:collapse;margin:14px 0;font-size:.85em;border-radius:var(--radius-sm);overflow:hidden;box-shadow:var(--shadow)}
table.info th,table.info td{border:1px solid var(--line-2);padding:8px 12px;text-align:left;vertical-align:top}
table.info th{background:var(--panel-2);color:var(--accent-2);font-weight:600}
table.info td{background:var(--panel)}

/* diff table */
table.diff{border-collapse:collapse;width:100%;font-family:var(--font-mono);font-size:.79em;line-height:1.6;
  background:var(--bg-elev);border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;box-shadow:var(--shadow)}
table.diff td{padding:0;vertical-align:top}
table.diff td.ln{width:1%;min-width:46px;text-align:right;padding:0 11px;color:var(--fg-3);
  background:var(--panel);user-select:none;border-right:1px solid var(--line);white-space:nowrap;font-variant-numeric:tabular-nums}
table.diff td.sg{width:16px;text-align:center;color:var(--fg-3);user-select:none;padding:0 2px;font-weight:700}
table.diff td.cd{padding:0 14px;white-space:pre-wrap;word-break:break-word;color:var(--fg)}
table.diff tr.add td.cd,table.diff tr.add td.sg{background:var(--add-bg);color:var(--add-fg)}
table.diff tr.del td.cd,table.diff tr.del td.sg{background:var(--del-bg);color:var(--del-fg)}
table.diff tr.add td.ln{background:var(--add-ln)}table.diff tr.del td.ln{background:var(--del-ln)}
table.diff tr.hunk td{background:var(--accent-soft);color:var(--accent-2);padding:4px 14px;
  border-top:1px solid var(--line);border-bottom:1px solid var(--line);font-size:.94em}
mark.wd{border-radius:3px;padding:0 1px;font-weight:600}
mark.wd-add{background:color-mix(in srgb,var(--sev-good) 42%,transparent);color:var(--fg)}
mark.wd-del{background:color-mix(in srgb,var(--sev-block) 42%,transparent);color:var(--fg)}
:root[data-theme="light"] mark.wd-add{background:#aef0c8}
:root[data-theme="light"] mark.wd-del{background:#ffc9c4}

.hint{color:var(--fg-3);font-size:.75em;margin-top:22px;line-height:2.1;max-width:920px}
kbd{background:var(--panel-2);border:1px solid var(--line-2);border-bottom-width:2px;border-radius:5px;
  padding:1px 6px;font-size:.9em;font-family:var(--font-mono);color:var(--fg-2)}

/* entrance animation */
@keyframes fadeUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style></head><body>
<div class="banner" id="banner">
  <span>⚠︎ Temporary file — <code>__OUT_PATH__</code> — delete after posting the comments and merging the PR</span>
  <span class="x" onclick="document.getElementById('banner').remove()">dismiss</span>
</div>
<header>
  <div class="head-top">
    <div>
      <div class="eyebrow">Pull Request Review</div>
      <h1>__PR_TITLE__</h1>
      <div class="meta">__PR_SUB__ &nbsp;·&nbsp; <b>__PR_COUNTS__</b></div>
    </div>
    <div class="tools">
      <div class="iconbtn" id="themebtn" title="Toggle light / dark theme"></div>
    </div>
  </div>
  <div class="chips" id="chips"></div>
  <div class="meter" id="meter"></div>
</header>
<div class="layout">
  <nav class="sidebar" id="sidebar">
    <div class="search"><div class="search-wrap">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>
      <input id="q" type="text" placeholder="Filter files…  ( / )" autocomplete="off">
    </div></div>
    <div class="filelist" id="filelist"></div>
  </nav>
  <div class="resizer" id="resizer" title="drag to resize (double-click to reset)"></div>
  <main class="content" id="content"><div class="content-inner" id="inner"></div></main>
</div>
<script>
const SEV={block:'b-block',high:'b-high',med:'b-med',low:'b-low',good:'b-good',new:'b-new'};
const SEVL={block:'BLOCKER',high:'HIGH',med:'MEDIUM',low:'NIT',good:'OK',new:'NEW'};
const SEVVAR={block:'--sev-block',high:'--sev-high',med:'--sev-med',low:'--sev-low',good:'--sev-good',new:'--sev-new'};
const ORDER_SEV=['block','high','med','low','good','new'];
const D=__PAYLOAD__;
const FILES=D.entries, GROUPS=D.groups, OVERVIEW=D.overview;
const ORDER=['__overview__',...FILES.map(f=>f.path)];
let state={id:'__overview__',tab:'context',q:'',hidden:{}};
let booted=false;
const cvar=v=>getComputedStyle(document.documentElement).getPropertyValue(v).trim();

/* ---- theme ---- */
const THKEY='pr_theme';
const ICON={sun:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
  moon:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>'};
function applyTheme(t){document.documentElement.setAttribute('data-theme',t);
  document.getElementById('themebtn').innerHTML=(t==='dark'?ICON.sun:ICON.moon)+`<span>${t==='dark'?'Light':'Dark'}</span>`;}
(function(){const saved=localStorage.getItem(THKEY);
  const t=saved||(matchMedia('(prefers-color-scheme: light)').matches?'light':'dark');applyTheme(t);})();
document.getElementById('themebtn').onclick=()=>{const t=document.documentElement.getAttribute('data-theme')==='dark'?'light':'dark';
  applyTheme(t);localStorage.setItem(THKEY,t);chips();meter();};

/* ---- header chips + meter ---- */
function tally(){const c={};FILES.forEach(f=>f.comments.forEach(cm=>{c[cm[0]]=(c[cm[0]]||0)+1;}));return c;}
function chips(){
  const c=tally();let h='';
  ORDER_SEV.forEach(k=>{if(c[k])h+=`<span class="chip ${state.hidden[k]?'off':''}" data-k="${k}"><span class="dot" style="background:${cvar(SEVVAR[k])}"></span><span class="n">${c[k]}</span> <span class="l">${SEVL[k]}</span></span>`;});
  h+=`<span class="chip" style="cursor:default"><span class="dot" style="background:var(--fg-3)"></span><span class="n">${FILES.length}</span> <span class="l">FILES</span></span>`;
  const el=document.getElementById('chips');el.innerHTML=h;
  el.querySelectorAll('.chip[data-k]').forEach(ch=>ch.onclick=()=>{const k=ch.dataset.k;state.hidden[k]=!state.hidden[k];chips();render();});
}
function meter(){
  const c=tally();const tot=Object.values(c).reduce((a,b)=>a+b,0);
  const el=document.getElementById('meter');
  if(!tot){el.style.display='none';return;}el.style.display='flex';
  el.innerHTML=ORDER_SEV.filter(k=>c[k]).map(k=>`<span style="width:${c[k]/tot*100}%;background:${cvar(SEVVAR[k])}" title="${c[k]} ${SEVL[k]}"></span>`).join('');
}

/* ---- sidebar ---- */
function counts(f){if(!f.add&&!f.del)return'';return `<span class="counts"><span class="a">+${f.add}</span> <span class="d">-${f.del}</span></span>`;}
function visible(f){
  const q=state.q.toLowerCase();
  const qok=!q||f.name.toLowerCase().includes(q)||f.path.toLowerCase().includes(q)||(f.walk||'').toLowerCase().includes(q);
  return qok;
}
function sidebar(){
  let h=`<div class="file-item ov-item ${state.id==='__overview__'?'active':''}" data-id="__overview__">
    <span class="seq">★</span><div class="fmeta"><div class="fname">Overview</div><div class="fwalk">summary + reading path</div></div></div>`;
  GROUPS.forEach(g=>{
    const items=FILES.filter(f=>f.group===g&&visible(f));
    if(!items.length)return;
    h+=`<div class="grouphdr">${g}</div>`;
    items.forEach(f=>{
      h+=`<div class="file-item ${state.id===f.path?'active':''}" data-id="${f.path}">
        <span class="seq">${f.seq}</span>
        <div class="fmeta"><div class="fname">${f.name}</div>${f.walk?`<div class="fwalk">${f.walk}</div>`:''}</div>
        <div class="fright"><span class="badge ${SEV[f.badge]}">${SEVL[f.badge]}</span>${counts(f)}</div>
      </div>`;
    });
  });
  const fl=document.getElementById('filelist');fl.innerHTML=h;
  const rows=fl.querySelectorAll('.file-item');
  rows.forEach((el,i)=>{el.onclick=()=>go(el.dataset.id);
    if(!booted){el.style.animation=`fadeUp .34s var(--ease) both`;el.style.animationDelay=(i*22)+'ms';}});
  booted=true;
}
function go(id){state.id=id;state.tab='context';render();
  const c=document.getElementById('content');c.scrollTop=0;}
function step(delta){const i=ORDER.indexOf(state.id);let j=i+delta;if(j<0||j>=ORDER.length)return;go(ORDER[j]);}

/* ---- content ---- */
function shownComments(f){return f.comments.filter(cm=>!state.hidden[cm[0]]);}
function render(){
  sidebar();
  const c=document.getElementById('content');
  const inner=document.createElement('div');inner.className='content-inner';inner.id='inner';

  if(state.id==='__overview__'){
    const cc=tally();const tf=FILES.length;
    const adds=FILES.reduce((a,f)=>a+f.add,0),dels=FILES.reduce((a,f)=>a+f.del,0);
    let stats=`<div class="stat"><div class="tick" style="background:var(--fg-3)"></div><div class="big">${tf}</div><div class="lab">Files</div></div>`;
    stats+=`<div class="stat"><div class="big"><span style="color:var(--add-fg)">+${adds}</span> <span style="color:var(--del-fg);font-size:.75em">-${dels}</span></div><div class="lab">Lines changed</div></div>`;
    ORDER_SEV.forEach(k=>{if(cc[k])stats+=`<div class="stat"><div class="tick" style="background:${cvar(SEVVAR[k])}"></div><div class="big" style="color:${cvar(SEVVAR[k])}">${cc[k]}</div><div class="lab">${SEVL[k]}</div></div>`;});

    let walk=`<h3>Reading path</h3><ol class="walk">`;
    FILES.forEach(f=>{walk+=`<li data-id="${f.path}"><span class="seq">${f.seq}</span><div class="wtxt"><span class="wname">${f.name}</span> <span class="badge ${SEV[f.badge]}">${SEVL[f.badge]}</span><div class="wdesc">${f.walk||''}</div></div></li>`;});
    walk+=`</ol>`;
    inner.innerHTML=`<div class="ov-hero"><h2><span class="star">★</span> Overview</h2></div>
      <div class="stat-grid">${stats}</div>${OVERVIEW}${walk}
      <div class="hint">Read in order — <kbd>j</kbd>/<kbd>k</kbd> or <kbd>←</kbd>/<kbd>→</kbd> navigate · <kbd>c</kbd> context · <kbd>r</kbd> review · <kbd>d</kbd> diff · <kbd>/</kbd> filter · <kbd>t</kbd> theme · click a severity chip to hide/show it · drag the sidebar edge to resize</div>`;
    swap(c,inner);
    inner.querySelectorAll('.walk li').forEach(el=>el.onclick=()=>go(el.dataset.id));
    inner.querySelectorAll('.stat-grid .stat').forEach((el,i)=>{el.style.animation='fadeUp .4s var(--ease) both';el.style.animationDelay=(i*40)+'ms';});
    return;
  }

  const f=FILES.find(x=>x.path===state.id);
  const i=ORDER.indexOf(state.id);
  const shown=shownComments(f);
  let h=`<div class="filehead"><h2 class="filetitle">${f.name} <span class="badge ${SEV[f.badge]}">${SEVL[f.badge]}</span></h2>
    <div class="navbtns">
      <div class="navbtn" ${i<=1?'disabled':''} onclick="step(-1)">← Prev</div>
      <div class="navbtn" ${i>=ORDER.length-1?'disabled':''} onclick="step(1)">Next →</div>
    </div></div>`;
  h+=`<div class="sub">${f.path}<span class="dotsep">·</span>step ${f.seq} of ${FILES.length}${f.add||f.del?`<span class="dotsep">·</span>`+counts(f):''}</div>`;
  h+=`<div class="tabs">
      <div class="tab ${state.tab==='context'?'active':''}" data-t="context">Context</div>
      <div class="tab ${state.tab==='review'?'active':''}" data-t="review">Review${shown.length?` <span class="tcount">${shown.length}</span>`:''}</div>
      <div class="tab ${state.tab==='diff'?'active':''}" data-t="diff">Full diff</div></div>`;
  if(f.note) h+=`<div class="note">${f.note}</div>`;
  if(state.tab==='context'){
    h+=f.context?`<div class="ctx-explain"><button class="copybtn" title="copy text" data-file="${f.path}" data-kind="Context" onclick="copyBox(this)">⧉ copy</button>${f.context}</div>`:`<div class="nocomment">No additional context for this file.</div>`;
  } else if(state.tab==='review'){
    if(shown.length){shown.forEach(cm=>{
      let gh='';
      if(cm[3]){gh=`<div class="gh"><div class="ghlabel"><span>GitHub comment</span><span class="copy" title="copy" onclick="navigator.clipboard.writeText(this.parentNode.nextElementSibling.innerText)">⧉</span></div><div class="ghtext">${cm[3]}</div></div>`;}
      h+=`<div class="comment c-${cm[0]}"><button class="copybtn" title="copy comment" data-file="${f.path}" data-kind="Review · ${SEVL[cm[0]]}" onclick="copyBox(this)">⧉ copy</button><div class="chead"><span class="badge ${SEV[cm[0]]}">${SEVL[cm[0]]}</span> ${cm[1]}</div><div class="cbody">${cm[2]}</div>${gh}</div>`;});}
    else h+=`<div class="nocomment">${f.comments.length?'All comments hidden by the severity filter.':'No comments — mechanical change.'}</div>`;
  } else { h+=f.diffHtml; }
  h+=`<div class="navbtns" style="margin-top:24px">
      <div class="navbtn" ${i<=1?'disabled':''} onclick="step(-1)">← Prev</div>
      <div class="navbtn" ${i>=ORDER.length-1?'disabled':''} onclick="step(1)">Next →</div></div>`;
  inner.innerHTML=h;
  swap(c,inner);
  inner.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{state.tab=t.dataset.t;render();});
}
function swap(container,inner){
  container.innerHTML='';container.appendChild(inner);
  if(!matchMedia('(prefers-reduced-motion: reduce)').matches)
    inner.animate([{opacity:0,transform:'translateY(6px)'},{opacity:1,transform:'none'}],{duration:240,easing:'cubic-bezier(.2,.7,.2,1)'});
}
function copyBox(btn){
  const box=btn.parentNode.cloneNode(true);
  const b=box.querySelector('.copybtn');if(b)b.remove();
  const body=(box.innerText||'').trim();
  const file=btn.dataset.file||'',kind=btn.dataset.kind||'';
  const header=(kind?`[${kind}] `:'')+file;
  const txt=header?`${header}\n\n${body}`:body;
  navigator.clipboard.writeText(txt).then(()=>{
    const old=btn.innerHTML;btn.classList.add('ok');btn.textContent='✓ copied';
    setTimeout(()=>{btn.classList.remove('ok');btn.innerHTML=old;},1200);
  });
}

/* ---- resizable sidebar ---- */
(function(){
  const sb=document.getElementById('sidebar'),rz=document.getElementById('resizer');
  const MIN=220,MAX=680,DEF=340,KEY='pr_sidebar_w';
  const saved=parseInt(localStorage.getItem(KEY)||'',10);
  if(saved>=MIN&&saved<=MAX)sb.style.width=saved+'px';
  let dragging=false;
  rz.addEventListener('mousedown',e=>{dragging=true;rz.classList.add('dragging');document.body.classList.add('resizing');e.preventDefault();});
  document.addEventListener('mousemove',e=>{if(!dragging)return;let w=Math.max(MIN,Math.min(MAX,e.clientX-sb.getBoundingClientRect().left));sb.style.width=w+'px';});
  document.addEventListener('mouseup',()=>{if(!dragging)return;dragging=false;rz.classList.remove('dragging');document.body.classList.remove('resizing');localStorage.setItem(KEY,parseInt(sb.style.width,10));});
  rz.addEventListener('dblclick',()=>{sb.style.width=DEF+'px';localStorage.setItem(KEY,DEF);});
})();

document.getElementById('q').addEventListener('input',e=>{state.q=e.target.value;sidebar();});
document.addEventListener('keydown',e=>{
  if(e.metaKey||e.ctrlKey||e.altKey)return;
  if(e.target.tagName==='INPUT'){if(e.key==='Escape')e.target.blur();return;}
  if(e.key==='j'||e.key==='ArrowRight'){step(1);e.preventDefault();}
  else if(e.key==='k'||e.key==='ArrowLeft'){step(-1);e.preventDefault();}
  else if(e.key==='/'){document.getElementById('q').focus();e.preventDefault();}
  else if(e.key==='t'){document.getElementById('themebtn').click();}
  else if(e.key==='c'||e.key==='d'||e.key==='r'){if(state.id!=='__overview__'){state.tab=(e.key==='c'?'context':e.key==='d'?'diff':'review');render();}}
});
chips();meter();render();
</script></body></html>
"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--diff", required=True)
    ap.add_argument("--review", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    build(a.diff, a.review, a.out)
