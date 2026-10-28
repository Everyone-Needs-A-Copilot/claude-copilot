# Setup and Resume

How to detect what is on disk, set up the design package in the current directory, and resume. Paths are relative to the project directory (the current directory) unless prefixed with `<skill-dir>`, the folder that contains the skill's SKILL.md.

---

## Step 0: Detect State

Run from the project directory:

```bash
ls docs/TODO-DESIGN-PACKAGE.md 2>/dev/null && echo RESUME
find docs -type f -name "*.md" -not -path "docs/_archive/*" 2>/dev/null | sort
```

| What you find | Path |
|---------------|------|
| `docs/TODO-DESIGN-PACKAGE.md` exists | Resume (below) |
| No `docs/` directory, or it holds no design material | Path 1: New product |
| `docs/` holds documents but no tracker | Path 2: Existing work |

If the folder is a repository that holds code or other documentation but no `docs/` design material, treat it as a new product: the design package is added next to the existing files and nothing is overwritten. If uncertain, ask: "Is this a new product, or are you continuing previous work?"

---

## Path 1: New Product (Start Fresh)

**Step 1: Ask for the product name and description.** Ask one question at a time: the product name, then a one-line description. The project directory is the current directory; do not ask for a path.

**Step 2: Create the docs directory and copy the template package.**

```bash
mkdir -p docs
tar -C "<skill-dir>/assets/templates" --exclude SOUL.md -cf - . | tar -C docs -xf -
```

`SOUL.md` is excluded on purpose: it is a root-level decision instrument, created at the project root during the soul DRAFT pass from `<skill-dir>/assets/templates/SOUL.md`, never inside `docs/`.

**Step 3: Replace the placeholders.** Replace `{{PRODUCT_NAME}}` with the product name, `{{PRODUCT_DESCRIPTION}}` with the one-line description and `{{SKILL_VERSION}}` with the skill version (the "Skill version" line in SKILL.md). Edit the files directly, or run this portable snippet with the values in the environment (it is safe for names containing `/`, `&` or quotes):

```bash
PRODUCT_NAME="<name>" PRODUCT_DESCRIPTION="<description>" SKILL_VERSION="1.0.0" python3 - <<'PY'
import os, pathlib
values = {
    "{{PRODUCT_NAME}}": os.environ["PRODUCT_NAME"],
    "{{PRODUCT_DESCRIPTION}}": os.environ["PRODUCT_DESCRIPTION"],
    "{{SKILL_VERSION}}": os.environ["SKILL_VERSION"],
}
for path in pathlib.Path("docs").rglob("*.md"):
    if "_archive" in path.parts:
        continue
    text = path.read_text(encoding="utf-8")
    new = text
    for key, value in values.items():
        new = new.replace(key, value)
    if new != text:
        path.write_text(new, encoding="utf-8")
PY
```

`{{STACK}}` (in the vision and design challenge brief) is not replaced at setup; it is answered during facilitation.

**Step 4: Begin facilitation.** Read `docs/TODO-DESIGN-PACKAGE.md`, the operational status tracker. Find the first document marked `NOT STARTED` and start there: Phase 1, Document 1, `docs/00-overview/00-vision.md`.

---

## Path 2: Existing Work (Archive, Overlay, Migrate)

Use this when `docs/` already holds design documentation that does not follow the template structure, or work was started without templates.

**Step 1: Assess what exists.** Read the current `docs/` and identify what is worth preserving: vision or overview, research and interview notes, journey maps, JTBD and service design artifacts, user stories or requirements, UX or UI notes, copy and voice guidance, and any design challenge or brief material.

**Step 2: Archive the existing docs.** Never delete existing work. Copy everything except earlier archives:

```bash
ARCHIVE="docs/_archive/$(date +%Y%m%d)-pre-template"
[ -e "$ARCHIVE" ] && echo "Archive already exists: $ARCHIVE" && exit 1
mkdir -p "$ARCHIVE"
find docs -mindepth 1 -maxdepth 1 ! -name _archive -exec cp -R {} "$ARCHIVE"/ \;
```

If the archive path exists, stop and ask the user before continuing. Verify the archive holds the same files as `docs/` before overlaying.

**Step 3: Copy the template package.** Same command as Path 1, Step 2. It overlays the template structure; existing files that match template paths are overwritten, and the originals are safe in the archive.

**Step 4: Replace the placeholders.** Same as Path 1, Step 3.

**Step 5: Migrate existing content.** For each archived document with real content (not stubs):

1. Read the archived version.
2. Read the corresponding new template (it holds the facilitation guide).
3. Map the existing content into the matching sections.
4. If existing content fully covers a section, fill it in and mark the section done.
5. If it is partial, fill in what exists and add `<!-- TODO: [what's missing] -->`.
6. Update the tracker status for each document.

**Migration mapping guide:**

| If the archive has... | It maps to... |
|----------------------|--------------|
| Vision, overview, product description | `00-overview/00-vision.md` |
| Scope, boundaries, non-goals | `00-overview/10-scope-and-non-goals.md` |
| Metrics, KPIs, success criteria | `00-overview/20-success-metrics.md` |
| Interview notes, user research | `01-research/10-interviews/` |
| JTBD, jobs to be done | `02-service-design/30-jtbd.md` |
| Journey maps, user flows | `02-service-design/20-journey-maps.md` |
| Moments that matter | `02-service-design/40-moments-that-matter.md` |
| Service blueprint | `02-service-design/10-service-blueprint.md` |
| User stories | `03-requirements/10-user-stories.md` |
| Use cases, scenarios | `03-requirements/20-use-cases-and-scenarios.md` |
| Acceptance criteria | `03-requirements/30-acceptance-criteria.md` |
| UX design, information architecture | `04-experience-design/50-ux-design.md` |
| UI design, visual direction | `04-experience-design/60-ui-design.md` |
| Copy, voice, tone | `04-experience-design/70-copy-voice.md` |
| Design challenge, creative brief | `05-design-challenge/00-brief.md` |
| An existing soul, principles or "what this product is not" | Root `SOUL.md`; see `soul-retrofit.md` |

**Step 6: Resume facilitation** as described below.

---

## Resume

1. Read `docs/TODO-DESIGN-PACKAGE.md`. Its "Created with" line records the skill version that built the package. If the major version differs from this skill's version, tell the user what may differ and ask before restructuring anything; never silently rewrite an existing package.
2. Find the first document marked `NOT STARTED` or `IN PROGRESS`.
3. For `IN PROGRESS` documents, read the content, find the last `<!-- SESSION BREAK -->` marker, identify which facilitation rounds are answered, and pick up at the next unanswered round.
4. Brief the user on where they are before asking anything: "We're on Document [#]: [name]. This is where we figure out [what]. Ready to start?"
5. If every facilitated document is complete, check whether `SOUL.md` is RATIFIED and whether a prototype output exists, and surface what is left.

The user can also say "Check docs/TODO-DESIGN-PACKAGE.md for where I left off" at the start of any session.

---

## After Setup: How the Facilitation Works

1. Each document has a facilitation guide embedded as HTML comments.
2. You ask the questions from the guide, one round at a time.
3. The user answers in their own words.
4. You synthesize the answers into the document.
5. Status is updated in `docs/TODO-DESIGN-PACKAGE.md`.
6. Move to the next document in sequence.

Phases 1 to 5 are facilitated: the user provides the content through conversation. Phase 6 is creation mode: you build the output the user chooses from everything documented in Phases 1 to 5.

## Reference

| Resource | Path | Purpose |
|----------|------|---------|
| Template package | `<skill-dir>/assets/templates/` | Document templates copied into `docs/` |
| Progress tracker | `docs/TODO-DESIGN-PACKAGE.md` | Operational status for all documents |
| Soul template | `<skill-dir>/assets/templates/SOUL.md` | Template for the root-level decision instrument |
| Soul facilitation guide | `soul-file.md` | Per-section interview questions, synthesis rules, Define-Done bar |
| Soul retrofit | `soul-retrofit.md` | Creating SOUL.md for a project that already has documentation or code |
| Prototype guides | `docs/06-prototype/` | One guide per prototype output, copied with the templates |
