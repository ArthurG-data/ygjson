# Automatic releases

## Intent

When a source changes (YGOPRODeck, TCGCSV, YGOJSON, the ban lists), the data on `main` is updated and a new
ygjson release is published, with no one merging, bumping or tagging. The checks are the only gate.

## Goals

- The weekly refresh, when the data changed and every check passed, commits to `main`, tags a release and publishes it
  with the same assets as a hand-made release.
- A refresh whose checks fail ships nothing; the run fails, and GitHub notifies the owner.
- A refresh that changes no data (sets/, data/, ids/, legality/) commits and releases nothing.

## Non-goals

- No change to how hand-made releases work: a `v*` tag pushed by a person still releases through `ci.yml`.
- No change to the refresh cadence (Mondays 07:00 UTC) or the sources it refreshes.

## Anti-goals

- A release whose tag, `pyproject.toml` version and README numbers disagree.
- A half-done run: data on `main` with no release, or a tag with no release, left without a failed run to say so.

## Approaches

1. **Fully automatic (chosen by the user):** the refresh workflow commits to `main`, tags and publishes itself.
2. One click: keep the refresh pull request; merging it triggers the release. Rejected: not hands-off.

## Design

- **Why the refresh publishes itself:** pushes and tags made with `GITHUB_TOKEN` start no other workflow, so the
  `ci.yml` release job would never see the refresh's tag. The release steps move to a reusable workflow
  (`release.yml`, `on: workflow_call`, input `tag`), which checks out that tag. `ci.yml`'s release job calls it
  on a pushed `v*` tag; `refresh.yml` calls it after pushing its tag.
- **Checks before anything is merged:** the refresh runs `pytest`, `validate.py` and `ids.py --check-against origin/main`.
- **Version (my call):** if the tag `v<pyproject version>` already exists, bump the patch number
  (`uv version --bump patch`, which also updates `uv.lock`); if it doesn't (a person bumped to 0.4.0 and has not
  tagged yet), release that version as it is. Then `stats.py --write` puts the new version and counts in the README.
- **Push (revised after review):** `main`'s ruleset (`protect-main`) takes changes only through a pull request and
  asks for no approval, so a direct push is refused. The refresh commits "Release X.Y.Z: refresh the sources (date)"
  to `refresh/sources`, opens or updates the pull request, checks `main` still is the commit it checked, merges the
  pull request itself, checks the merge holds exactly the checked tree, then tags the merge `vX.Y.Z`. If `main` moved,
  the run fails without merging or tagging. `release.yml` can also be run by hand for a tag that was never released.
- **Notes (my call):** the refresh summary (what `refresh_summary.py` writes for the pull request today) is added to
  the release notes after the id changes.
- **README:** the hand-written `"version": "0.3.0"` example becomes version-neutral, so it never goes stale; the release
  section describes the automatic releases.

## Left to the builder

- How the summary reaches the release job (an input, or regenerated in the release job against the previous tag).
- Whether `--generate-notes` stays (it lists pull requests; an automatic release has none of its own).
