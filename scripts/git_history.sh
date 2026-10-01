#!/usr/bin/env bash
# Persist and restore git history as a bundle file inside the working tree.
#
# Why this exists -- the measured problem, not a hypothetical one:
# this project is developed in a sandbox whose snapshots restore the WORKING TREE but roll
# `.git` back to a fixed baseline commit. Observed twice, identically: the tree came back with
# every edited file intact while `git log` and even `git reflog` returned to a634935, losing
# every commit made during the session. The reflog is the tell -- HEAD@{0} was the baseline
# commit, so the objects were never written back rather than being written and then rewound.
#
# The consequence is not cosmetic. DocScout is judged partly on a visible commit thread showing
# a defect caught, fixed and regression-tested (artifact 5), and a repository whose history
# truncates at the baseline cannot show one. Losing history also destroys the provenance that
# every eval number is supposed to carry.
#
# The fix follows the evidence: whatever is a plain file in the tree survives, so history is
# written to a plain file in the tree. `git bundle` is exactly that -- a single file holding
# all reachable objects plus refs, verifiable and clonable on its own.
#
# Rejected alternatives:
#   - A git remote (GitHub). The honest blocker: no PAT, and the user has ruled out remotes.
#   - Committing a tarball of `.git` into `.git`. Recursive, unboundedly large, and a bundle
#     is the purpose-built form of the same idea.
#   - `git gc` to pack objects, on a theory that a file-count cap was dropping loose objects.
#     Measured and rejected: 734 files / 44 MB in the whole home directory, far under the
#     documented ~10,000-file and ~128 MB caps, and the reflog loss disproves truncation.
#   - Copying `.git` to a sibling directory. Works, but stores thousands of loose object files
#     where one file does; a bundle also self-verifies via `git bundle verify`.
#
# Usage:  ./scripts/git_history.sh save     # write .history/docscout.bundle from all refs
#         ./scripts/git_history.sh restore  # fast-forward refs from the bundle (tree untouched)
#         ./scripts/git_history.sh status   # compare repo HEAD against the bundle

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUNDLE_DIR="$REPO_ROOT/.history"
BUNDLE="$BUNDLE_DIR/docscout.bundle"
MANIFEST="$BUNDLE_DIR/manifest.txt"
BRANCH=master

say() { printf '  %-22s %s\n' "$1" "${2-}"; }
die() { printf 'error: %s\n' "$1" >&2; exit 1; }

cd "$REPO_ROOT"

bundle_head() {
  # The bundle's tip for $BRANCH, or empty when the bundle is absent or unreadable.
  #
  # The `|| true` is load-bearing. Under `set -o pipefail` a corrupt bundle makes
  # `git bundle list-heads` fail, which fails the pipeline, which trips `set -e` and kills
  # the script with status 1 and not one word of output -- the single worst way for a
  # disaster-recovery tool to behave. Swallow it here and let cmd_restore diagnose it.
  [[ -f "$BUNDLE" ]] || return 0
  local heads
  heads="$(git bundle list-heads "$BUNDLE" 2>/dev/null || true)"
  awk -v b="refs/heads/$BRANCH" '$2==b {print $1}' <<<"$heads"
}

cmd_save() {
  git rev-parse --verify "$BRANCH" >/dev/null 2>&1 || die "branch $BRANCH does not exist"
  mkdir -p "$BUNDLE_DIR"
  # --all captures every branch and tag. Written to a temp file first so an interrupted run
  # cannot leave a truncated bundle in place of a good one.
  git bundle create "$BUNDLE.tmp" --all >/dev/null 2>&1 || die "git bundle create failed"
  git bundle verify "$BUNDLE.tmp" >/dev/null 2>&1 || { rm -f "$BUNDLE.tmp"; die "bundle failed verification"; }
  mv "$BUNDLE.tmp" "$BUNDLE"

  local head count
  head="$(git rev-parse HEAD)"
  count="$(git rev-list --count HEAD)"
  {
    echo "# DocScout git history bundle -- regenerate with ./scripts/git_history.sh save"
    echo "saved_utc   $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "branch      $BRANCH"
    echo "head        $head"
    echo "commits     $count"
    echo "bundle_sha  $(sha256sum "$BUNDLE" | cut -d' ' -f1)"
    echo "bundle_size $(stat -c%s "$BUNDLE") bytes"
  } > "$MANIFEST"

  say "saved" "$count commits, head ${head:0:7}"
  say "bundle" ".history/docscout.bundle ($(du -h "$BUNDLE" | cut -f1))"
}

cmd_restore() {
  # Diagnose corruption before anything else: a present-but-unreadable bundle is a louder
  # problem than an absent one, and must not be reported as "nothing to restore".
  if [[ -f "$BUNDLE" ]] && ! git bundle verify "$BUNDLE" >/dev/null 2>&1; then
    die "bundle at .history/docscout.bundle is corrupt; refusing to restore"
  fi

  local bh
  bh="$(bundle_head)"
  [[ -n "$bh" ]] || { say "restore" "no bundle at .history/ -- nothing to restore"; return 0; }

  if git cat-file -e "$bh^{commit}" 2>/dev/null && git merge-base --is-ancestor "$bh" HEAD 2>/dev/null; then
    say "restore" "repo already at or ahead of the bundle (${bh:0:7})"
    return 0
  fi

  git fetch -q "$BUNDLE" "refs/heads/*:refs/remotes/history/*" 2>/dev/null \
    || die "could not fetch objects from the bundle"

  # Refuse to rewrite history that the bundle does not contain: if HEAD has commits the bundle
  # lacks, a reset would discard them. Only ever fast-forward.
  if ! git merge-base --is-ancestor HEAD "$bh" 2>/dev/null; then
    say "restore" "SKIPPED -- HEAD has commits the bundle lacks; run 'save' instead"
    return 0
  fi

  local before after
  before="$(git rev-list --count HEAD)"
  # --mixed, NOT --soft. Both leave the working tree untouched, which is the requirement:
  # the tree is the surviving copy. The difference is the index, and --soft leaves it pinned
  # to the baseline commit. After the branch pointer jumps forward over commits that ADD
  # files, an index still describing the old commit reports every one of those files as a
  # staged deletion AND as untracked -- 60+ phantom changes on a tree that is in fact
  # identical to the restored HEAD. --mixed resets the index to match the new HEAD and still
  # never writes to the working tree.
  #
  # Not caught by simulating the reset with `git reset --soft <baseline>`: that leaves an
  # index consistent with the tree, so the round trip cancels out. A real restored session
  # begins with an index belonging to the baseline commit, which is the case that breaks.
  # A simulation has to reproduce the index state, not only the ref state.
  git reset -q --mixed "$bh"
  after="$(git rev-list --count HEAD)"
  say "restored" "$before -> $after commits, head ${bh:0:7}"
  say "working tree" "untouched (git reset --soft)"
}

cmd_status() {
  local bh rh
  bh="$(bundle_head)"; rh="$(git rev-parse HEAD 2>/dev/null || echo none)"
  say "repo head" "${rh:0:7} ($(git rev-list --count HEAD 2>/dev/null || echo 0) commits)"
  if [[ -z "$bh" ]]; then say "bundle" "absent"; return 0; fi
  say "bundle head" "${bh:0:7}"
  if [[ "$bh" == "$rh" ]]; then say "state" "in sync"
  elif git cat-file -e "$bh^{commit}" 2>/dev/null && git merge-base --is-ancestor "$bh" HEAD 2>/dev/null; then
    say "state" "repo is AHEAD of the bundle -- run 'save'"
  else say "state" "bundle is ahead or diverged -- run 'restore'"; fi
}

case "${1-}" in
  save)    cmd_save ;;
  restore) cmd_restore ;;
  status)  cmd_status ;;
  *) die "usage: $0 {save|restore|status}" ;;
esac
