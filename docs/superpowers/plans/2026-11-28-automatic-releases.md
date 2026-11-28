# Automatic Releases Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The weekly refresh, when the data changed and every check passed, commits to `main`, tags and publishes a release itself.

**Architecture:** A small tool (`tools/next_version.py`) picks the version to release. The release steps move from
`ci.yml` into a reusable workflow (`release.yml`, `workflow_call`) that checks out a given tag; `ci.yml` calls it on a
pushed `v*` tag, `refresh.yml` calls it after pushing its own commit and tag atomically.

**Tech Stack:** Python 3.11, uv, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-28-automatic-releases-design.md`

## Global Constraints

- Pushes and tags made with `GITHUB_TOKEN` start no other workflow: the refresh must call `release.yml` itself.
- Patch bump only when `v<pyproject version>` is already tagged; otherwise release the version as it is.
- Commit message: `Release X.Y.Z: refresh the sources (YYYY-MM-DD)`; tag `vX.Y.Z`; commit author `github-actions[bot]`.
- The commit and the tag are pushed with one `git push --atomic`: never a tag without its commit on `main`, or the reverse.
- A hand-pushed `v*` tag releases exactly as today (tag/pyproject check, build, changelog, package, `gh release create`).
- Every action stays pinned to a commit SHA with its release in a comment (the SHAs already in the workflows).

## Review Focus

- `main` moved during the run → the atomic push is rejected, the run fails, nothing is tagged or released.
- A manual dispatch from a branch other than `main` → checks run, nothing is pushed or released.
- A person bumped pyproject to 0.4.0 and has not tagged → the refresh releases 0.4.0, not 0.4.1 (Task 1 test).
- The release job fails after the tag was pushed → "Re-run failed jobs" on that run publishes it (the reusable
  workflow checks out the tag, not `main`); the README says so.
- A refresh that changes no data → no version bump, no commit, no release.

---

### Task 1: `tools/next_version.py`

**Files:**
- Create: `tools/next_version.py`
- Test: `tests/test_next_version.py`

**Interfaces:**
- Produces: `next_version(current: str, tagged: bool) -> str`; `is_tagged(version: str, root: Path = ygjson.ROOT) -> bool`
  (true when `refs/tags/v<version>` exists); CLI `uv run python tools/next_version.py` prints the version and appends
  `version=<v>` to `$GITHUB_OUTPUT` when set. It reads the version with `stats._version`. It changes no file.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_tagged_version_gets_the_next_patch():
    assert next_version.next_version("0.3.0", tagged=True) == "0.3.1"
    assert next_version.next_version("0.4.9", tagged=True) == "0.4.10"

def test_an_untagged_version_is_released_as_it_is():
    assert next_version.next_version("0.4.0", tagged=False) == "0.4.0"

def test_a_version_that_is_not_three_numbers_is_refused():
    with pytest.raises(ValueError):
        next_version.next_version("0.3.0-dev", tagged=True)

def test_is_tagged_reads_the_repository(tmp_path):  # git init, commit, tag v1.0.0
    assert next_version.is_tagged("1.0.0", tmp_path) and not next_version.is_tagged("1.0.1", tmp_path)
```

- [ ] **Step 2:** `uv run pytest tests/test_next_version.py -q` → fails (no module).
- [ ] **Step 3:** Implement; module docstring in the style of the other tools (usage line first).
- [ ] **Step 4:** `uv run pytest -q && uv run ruff check && uv run mypy` → pass.
- [ ] **Step 5:** Commit `Pick the version an automatic release takes`.

### Task 2: Workflows and README

**Files:**
- Create: `.github/workflows/release.yml`
- Modify: `.github/workflows/ci.yml` (release job), `.github/workflows/refresh.yml`, `README.md`

**Interfaces:**
- Consumes: `tools/next_version.py` (Task 1).
- Produces: `release.yml` with `on: workflow_call`, inputs `tag` (string, required) and `notes` (string, default `''`,
  appended to the release notes after `dist/CHANGES.md`). It needs `contents: write` from its caller.

- [ ] **Step 1: `release.yml`.** The steps of today's `ci.yml` release job, with `actions/checkout` at
  `ref: ${{ inputs.tag }}` and every `GITHUB_REF_NAME` replaced by `inputs.tag` (passed through `env:`, never
  interpolated into a script). Notes file: `dist/CHANGES.md`, then a blank line and `inputs.notes` when non-empty.
  Keep `--generate-notes`.
- [ ] **Step 2: `ci.yml`.** The release job becomes `needs: validate`, same `if`, `permissions: contents: write`,
  `uses: ./.github/workflows/release.yml`, `with: tag: ${{ github.ref_name }}`.
- [ ] **Step 3: `refresh.yml`.**
  - Header comment rewritten for the new flow; `permissions` of the job: `contents: write` only.
  - Add `uv run pytest -q` to the checks.
  - Summary step: `--base HEAD` as now (its `changed` output decides).
  - When changed and `github.ref == 'refs/heads/main'`: `next_version.py` (id `version`), `uv version "$VERSION"`
    (updates pyproject and uv.lock), `stats.py --write`, `stats.py` (check), commit
    `git add sets data ids legality review sources.json README.md pyproject.toml uv.lock`, `git tag "v$VERSION"`,
    `git push --atomic origin HEAD:main "v$VERSION"`. The job outputs `tag` and `notes` (the summary body, written to
    `$GITHUB_OUTPUT` with a random heredoc delimiter).
  - Second job `release`: `needs: refresh`, `if: needs.refresh.outputs.tag != ''`, `permissions: contents: write`,
    `uses: ./.github/workflows/release.yml` with `tag` and `notes`.
  - Remove the pull-request step and the `BRANCH` env.
- [ ] **Step 4: README.** Line 30's example version becomes `"X.Y.Z"`. The CI paragraph about `refresh.yml` describes
  the automatic release (checks, version rule, atomic push, re-run failed jobs when the release job fails, no refresh
  PR any more); remove the "allow GitHub Actions to create pull requests" sentence.
- [ ] **Step 5: Verify.** `python -c` parse of the three YAML files with `yaml.safe_load` (or `actionlint` if present);
  `uv run pytest -q`, `ruff`, `mypy`, `validate.py`, `stats.py` → pass. Commit `Release automatically when a refresh
  changes the data`, with the spec and this plan.
