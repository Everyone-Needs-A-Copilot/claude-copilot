"""`cc survival` -- what fraction of what the agents wrote is still there.

WHY THIS EXISTS.

Every gate in this framework asks "was the method followed?" FF1-FF12 check the
corpus. Conformance checks the install. The QA gate checks that evidence was
attached. Not one of them asks "was the result any good?" -- which is why the
framework can pass all of its own checks while still not feeling like it pays off,
and why SOUL.md's Principle 4 concedes it lacks the rework data that would let it
claim better software.

The owner's own formulation is the metric: **if I don't change it, it's good; if I
change it, it's not.** That is computable from git alone. No rubric, no rating,
nobody asked anything, and -- the part that matters -- it cannot be gamed by the
thing being measured. An edit is a physical act on a file, not a verbal reaction
that a persuasive agent or a taste corpus could shape.

WHAT IS ACTUALLY COMPUTED.

  authored    lines added by agent-authored commits, from --numstat
  surviving   lines at HEAD that `git blame` still attributes to those commits
  survival    surviving / authored

An agent commit is one carrying a `Co-Authored-By:` trailer naming an assistant.
That is this ecosystem's real marker, present on every commit the framework makes,
and it is read from the commit rather than inferred from the diff.

WHAT THIS NUMBER IS NOT.

It is a rework proxy, not a quality score, and four things blur it. Said plainly
here because a metric whose limits live only in someone's head is how "0.72" turns
into "72% good".

  1. A moved line reads as a changed line. Reformatting, a rename sweep, or a
     linter pass all depress survival without anyone judging the work.
  2. Lines in files later deleted count as authored and never as surviving. A
     deleted prototype scores 0 whether it was wrong or simply finished.
  3. Survival rises with time-since-authoring only up to a point, then falls as
     ordinary maintenance rewrites old code. Comparing a fresh branch against a
     two-year-old one compares ages, not quality.
  4. High survival can mean nobody looked. Untouched and unreviewed are the same
     shape from here.

Which is why `--by-window` exists: comparing framework-era work against
pre-framework work at similar ages is the comparison worth making, and it is still
confounded, because framework sessions may simply be different kinds of work. It
remains a better experiment than anything synthetic, because "did you change it"
only exists in real work.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import typer

survival_app = typer.Typer(
    no_args_is_help=False,
    help="What fraction of agent-authored lines survive untouched (git-only, no rubric).",
)

# The trailer the framework actually writes. Matched case-insensitively on the
# assistant name rather than an exact model string, so a model rename does not
# silently reclassify history as human-authored -- that failure would be invisible
# and would inflate every number here.
AGENT_TRAILER = re.compile(
    r"^\s*co-authored-by:\s*(claude|codex|gpt|assistant)\b", re.IGNORECASE | re.MULTILINE
)

# Files whose survival says nothing about judgement: generated output, locks, and
# vendored trees are rewritten wholesale by tools.
EXCLUDED = re.compile(
    r"(^|/)(node_modules|\.venv|dist|build|__pycache__|vendor)(/|$)"
    r"|\.(lock|min\.js|min\.css|map|png|jpe?g|gif|svg|ico|woff2?|ttf|pdf)$"
    r"|(^|/)(package-lock\.json|uv\.lock|poetry\.lock|yarn\.lock|copilot\.lock\.json)$"
)

# Framework-installed files, excluded by DEFAULT -- and this exclusion is the
# difference between a metric and a misleading number.
#
# The first run of this command on a real project reported 47.4% survival, and the
# three lowest-survival files were `.claude/commands/config.md`,
# `knowledge-copilot.md` and `reflect.md` at 0%, with 596 of 797 files "deleted
# since". None of that is rework of anything anyone judged. Those files are
# installed by the framework and replaced wholesale on every update, so their
# survival measures the framework's own release cadence and nothing about the work.
# Left in, they would have dominated the figure on exactly the projects that use
# the framework most -- reporting heavy framework adoption as poor quality.
FRAMEWORK_INSTALLED = re.compile(
    r"(^|/)(\.claude|\.codex|\.copilot|\.agents)(/|$)"
    r"|(^|/)plugins/(claude|codex)-copilot(/|$)"
    r"|(^|/)(CLAUDE\.md|AGENTS\.md|copilot\.project\.json|copilot\.layer\.yml)$"
)


@dataclass
class Bucket:
    authored: int = 0
    surviving: int = 0
    commits: set[str] = field(default_factory=set)

    @property
    def rate(self) -> float | None:
        return (self.surviving / self.authored) if self.authored else None


def _git(repo: Path, *args: str, timeout: int = 300) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=timeout, check=False,
    )
    if out.returncode != 0:
        return ""
    return out.stdout


def agent_commits(repo: Path, since: str | None) -> dict[str, dict]:
    """Every agent-authored commit, with its date. Read from trailers, not diffs."""
    args = ["log", "--no-merges", "--format=%H%x00%aI%x00%B%x1e"]
    if since:
        args.append(f"--since={since}")
    raw = _git(repo, *args)
    found: dict[str, dict] = {}
    for record in raw.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        parts = record.split("\x00", 2)
        if len(parts) < 3:
            continue
        sha, date, body = parts
        if AGENT_TRAILER.search(body):
            found[sha] = {"date": date, "subject": body.strip().splitlines()[0] if body.strip() else ""}
    return found


def authored_lines(
    repo: Path, shas: set[str], include_framework: bool = False
) -> tuple[int, dict[str, int]]:
    """Lines added by these commits, total and per file."""
    total = 0
    per_file: dict[str, int] = defaultdict(int)
    for sha in shas:
        raw = _git(repo, "show", "--numstat", "--format=", sha)
        for line in raw.splitlines():
            cols = line.split("\t")
            if len(cols) != 3 or cols[0] == "-":
                continue        # binary, or a malformed row
            added, _removed, path = cols
            if EXCLUDED.search(path):
                continue
            if not include_framework and FRAMEWORK_INSTALLED.search(path):
                continue
            try:
                n = int(added)
            except ValueError:
                continue
            total += n
            per_file[path] += n
    return total, dict(per_file)


def surviving_lines(repo: Path, shas: set[str], paths: list[str]) -> tuple[int, dict[str, int]]:
    """Lines still at HEAD that blame attributes to these commits."""
    total = 0
    per_file: dict[str, int] = {}
    for path in paths:
        if not (repo / path).is_file():
            continue        # deleted since; counts as authored, never as surviving
        raw = _git(repo, "blame", "--line-porcelain", "--", path)
        if not raw:
            continue
        count = sum(
            1 for line in raw.splitlines()
            if len(line) >= 40 and line[:40] in shas and " " in line
            and line.split(" ", 1)[0] in shas
        )
        if count:
            per_file[path] = count
            total += count
    return total, per_file


@survival_app.callback(invoke_without_command=True)
def survival(
    repo: Path = typer.Option(Path("."), "--repo", help="Repository to measure."),
    since: str | None = typer.Option(
        None, "--since", help="Only consider commits after this date (git --since syntax)."
    ),
    include_framework: bool = typer.Option(
        False, "--include-framework",
        help="Also count framework-installed files (.claude/, plugins/, CLAUDE.md). "
             "Off by default: those are replaced wholesale on every framework update, "
             "so their survival measures release cadence, not the work.",
    ),
    by_window: bool = typer.Option(
        False, "--by-window",
        help="Split by authoring year, so eras are compared at comparable ages.",
    ),
    top: int = typer.Option(0, "--top", help="Also show the N lowest-survival files."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Report agent-authored line survival for a repository."""
    repo = repo.expanduser().resolve()
    if not (repo / ".git").exists():
        typer.echo(f"Not a git repository: {repo}", err=True)
        raise typer.Exit(2)

    commits = agent_commits(repo, since)
    if not commits:
        payload = {
            "repo": str(repo),
            "agent_commits": 0,
            "detail": "No commits carry a Co-Authored-By trailer naming an assistant.",
        }
        if as_json:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(
                f"{repo.name}: no agent-authored commits found.\n"
                f"This measures commits carrying a `Co-Authored-By:` trailer naming an "
                f"assistant. A repo where the agent's work was committed without one is "
                f"invisible here -- absence of a number is not a survival rate of zero."
            )
        raise typer.Exit(0)

    shas = set(commits)
    authored_total, authored_per_file = authored_lines(repo, shas, include_framework)
    surviving_total, surviving_per_file = surviving_lines(
        repo, shas, sorted(authored_per_file)
    )

    if authored_total == 0:
        message = (
            f"{repo.name}: {len(commits)} agent commit(s), but no product lines to "
            f"measure. Every line they added is in a framework-installed or generated "
            f"path, which is excluded because those files are replaced wholesale on "
            f"update. Pass --include-framework to see that churn; it is not a quality "
            f"signal."
        )
        if as_json:
            typer.echo(json.dumps({"repo": str(repo), "agent_commits": len(commits),
                                   "authored_lines": 0, "survival_rate": None,
                                   "detail": message}, indent=2))
        else:
            typer.echo(message)
        raise typer.Exit(0)

    result: dict = {
        "repo": str(repo),
        "agent_commits": len(commits),
        "authored_lines": authored_total,
        "surviving_lines": surviving_total,
        "survival_rate": round(surviving_total / authored_total, 4) if authored_total else None,
        "files_touched": len(authored_per_file),
        "framework_files_included": include_framework,
        "files_deleted_since": sum(
            1 for p in authored_per_file if not (repo / p).is_file()
        ),
    }

    if by_window:
        buckets: dict[str, Bucket] = defaultdict(Bucket)
        for sha, meta in commits.items():
            buckets[meta["date"][:4]].commits.add(sha)
        windows = {}
        for year, bucket in sorted(buckets.items()):
            a_total, a_files = authored_lines(repo, bucket.commits, include_framework)
            s_total, _ = surviving_lines(repo, bucket.commits, sorted(a_files))
            windows[year] = {
                "commits": len(bucket.commits),
                "authored_lines": a_total,
                "surviving_lines": s_total,
                "survival_rate": round(s_total / a_total, 4) if a_total else None,
            }
        result["by_year"] = windows

    if top:
        ranked = sorted(
            (
                (p, authored_per_file[p], surviving_per_file.get(p, 0))
                for p in authored_per_file
                if authored_per_file[p] >= 10        # a 3-line file's rate is noise
            ),
            key=lambda r: (r[2] / r[1]) if r[1] else 1.0,
        )
        result["lowest_survival_files"] = [
            {"path": p, "authored": a, "surviving": s, "rate": round(s / a, 4)}
            for p, a, s in ranked[:top]
        ]

    if as_json:
        typer.echo(json.dumps(result, indent=2))
        raise typer.Exit(0)

    rate = result["survival_rate"]
    typer.echo(f"{repo.name}")
    typer.echo(f"  agent commits      {result['agent_commits']:,}")
    typer.echo(f"  lines authored     {authored_total:,}")
    typer.echo(f"  lines surviving    {surviving_total:,}")
    typer.echo(f"  survival rate      {rate:.1%}" if rate is not None else
               "  survival rate      n/a")
    if result["files_deleted_since"]:
        typer.echo(
            f"  files since deleted {result['files_deleted_since']} of "
            f"{result['files_touched']} — their lines count as authored and never as "
            f"surviving, so a finished prototype depresses this figure"
        )

    if by_window:
        typer.echo("\n  by authoring year (compare eras at comparable ages, not across them)")
        for year, w in result["by_year"].items():
            r = w["survival_rate"]
            typer.echo(
                f"    {year}  {w['commits']:>4} commits  {w['authored_lines']:>8,} authored  "
                + (f"{r:.1%}" if r is not None else "n/a")
            )

    if top and result.get("lowest_survival_files"):
        typer.echo(f"\n  lowest survival ({top} files, >=10 authored lines)")
        for row in result["lowest_survival_files"]:
            typer.echo(f"    {row['rate']:>6.1%}  {row['authored']:>6,} authored  {row['path']}")

    typer.echo(
        "\n  Read this as a rework proxy, not a quality score. A moved or reformatted line "
        "reads as a changed one; lines in deleted files never survive; and high survival can "
        "equally mean nobody looked. It earns its place by being the one measure the thing "
        "being measured cannot influence -- an edit is a physical act on a file, not a "
        "reaction an agent can shape."
    )
