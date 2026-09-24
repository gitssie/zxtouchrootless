#!/bin/sh

# Local build, isolated gh-pages checkout, ordinary non-force push.
set -eu
umask 077

export GIT_TERMINAL_PROMPT=0
export GCM_INTERACTIVE=Never
export GIT_ASKPASS=true
export SSH_ASKPASS=true
GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh} -o BatchMode=yes -o StrictHostKeyChecking=yes"
export GIT_SSH_COMMAND

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
expected_remote=git@github.com:gitssie/zxtouchrootless.git
tmp=""
dry_run=0
skip_build=0
publish_seen=0

usage() {
    cat <<'EOF'
Usage: scripts/publish_github_pages.sh [--dry-run] [--skip-build] publish

Build both ZXTouch packages locally, validate a Sileo APT repository, then
commit and non-force push it to gh-pages without switching the main worktree.
--skip-build uses the two current-version packages already in packages/.
GitHub Pages must serve the gh-pages branch from /(root).
EOF
}

fail() { echo "error: $*" >&2; exit 1; }
cleanup() { [ -z "$tmp" ] || rm -rf "$tmp"; }
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

for arg in "$@"; do
    case "$arg" in *'
'*) fail "arguments must not contain newlines" ;; esac
done
while [ "$#" -gt 0 ]; do
    case "$1" in
        --dry-run) dry_run=1; shift ;;
        --skip-build) skip_build=1; shift ;;
        publish) publish_seen=1; shift; [ "$#" -eq 0 ] || fail "unexpected argument"; break ;;
        -h|--help) usage; exit 0 ;;
        *) fail "unknown argument: $1" ;;
    esac
done
[ "$publish_seen" -eq 1 ] || fail "publish command is required"

for command_name in git python3 zstd xcodebuild ldid make mktemp; do
    command -v "$command_name" >/dev/null 2>&1 || fail "missing $command_name"
done

[ "$(git -C "$root" branch --show-current)" = main ] || fail "publish from main"
[ "$(git -C "$root" remote get-url origin)" = "$expected_remote" ] ||
    fail "origin must be $expected_remote"

version=$(awk -F': ' '$1 == "Version" { print $2; exit }' "$root/control")
[ -n "$version" ] || fail "control has no Version"
rootless="$root/packages/com.zjx.ioscontrol_${version}_rootless.deb"
roothide="$root/packages/com.zjx.ioscontrol_${version}_roothide.deb"

if [ "$dry_run" -eq 1 ]; then
    echo "source=$root"
    echo "remote=$expected_remote"
    echo "version=$version"
    echo "build=$([ "$skip_build" -eq 1 ] && echo existing-packages || echo both-architectures)"
    echo "pages=https://gitssie.github.io/zxtouchrootless"
    exit 0
fi

assert_source_state() {
    [ -z "$(git -C "$root" status --porcelain --untracked-files=normal)" ] ||
        fail "main worktree must be clean"
    local_head=$(git -C "$root" rev-parse HEAD)
    remote_head=$(git ls-remote --heads "$expected_remote" refs/heads/main | awk 'NR == 1 {print $1}')
    [ -n "$remote_head" ] || fail "remote main is unavailable"
    [ "$local_head" = "$remote_head" ] || fail "local main must match origin/main"
}

assert_source_state
release_head=$(git -C "$root" rev-parse HEAD)

if [ "$skip_build" -eq 0 ]; then "$root/scripts/build_packages.sh"; fi
[ -f "$rootless" ] && [ -f "$roothide" ] || fail "both packages are required"
assert_source_state
[ "$(git -C "$root" rev-parse HEAD)" = "$release_head" ] || fail "main changed during build"

tmp=$(mktemp -d "${TMPDIR:-/tmp}/zxtouch-pages.XXXXXX")
mkdir -p "$tmp/site" "$tmp/git"
python3 "$root/scripts/render_github_pages.py" \
    --rootless "$rootless" --roothide "$roothide" --output "$tmp/site"

git -C "$tmp/git" init --quiet
git -C "$tmp/git" remote add origin "$expected_remote"
if [ -n "$(git ls-remote --heads "$expected_remote" refs/heads/gh-pages)" ]; then
    git -C "$tmp/git" fetch --quiet --depth=1 origin gh-pages
    git -C "$tmp/git" checkout --quiet -B gh-pages FETCH_HEAD
    git -C "$tmp/git" rm -r -f --ignore-unmatch . >/dev/null
else
    git -C "$tmp/git" checkout --quiet --orphan gh-pages
fi
cp -Rf "$tmp/site/." "$tmp/git/"
git -C "$tmp/git" add --all
assert_source_state
[ "$(git -C "$root" rev-parse HEAD)" = "$release_head" ] || fail "main changed during rendering"

if git -C "$tmp/git" diff --cached --quiet; then
    echo "already_published=$version"
    exit 0
fi

git_user_name=$(git -C "$root" config user.name || true)
git_user_email=$(git -C "$root" config user.email || true)
[ -n "$git_user_name" ] && [ -n "$git_user_email" ] || fail "Git author identity is missing"
git -C "$tmp/git" -c "user.name=$git_user_name" -c "user.email=$git_user_email" \
    commit --quiet -m "repo: publish ZXTouch $version"
assert_source_state
git -C "$tmp/git" push origin HEAD:refs/heads/gh-pages
echo "published_version=$version"
echo "sileo_source=https://gitssie.github.io/zxtouchrootless"
