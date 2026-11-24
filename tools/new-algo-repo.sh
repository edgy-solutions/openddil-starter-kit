#!/usr/bin/env bash
# Create a PRIVATE GitHub repo for your own algorithm work, seeded from this
# starter kit, with the recording fetched and checked and the tests run.
#
#   tools/new-algo-repo.sh [options] OWNER/NAME
#
#   tools/new-algo-repo.sh my-org/my-algorithms
#   tools/new-algo-repo.sh --host github.example.com my-team/my-algorithms
#
# OWNER is your own account or an organization you can create repos in.
# Run it from the folder the new checkout should be created in. It doesn't
# need the GitHub CLI (gh). It needs git, curl, tar, python 3.11+, and
# sha256sum or shasum.
#
# Options:
#   --host HOST          GitHub host. Default github.com. For GitHub Enterprise
#                        Server, your server's host name.
#   --api-url URL        API base, when it isn't https://api.github.com (for
#                        github.com) or https://HOST/api/v3 (for any other host).
#   --dir DIR            checkout folder. Default ./NAME.
#   --description TEXT   the new repo's description.
#   --use-existing       use a repo that already exists, is private and is
#                        empty, instead of creating one. Use this when your
#                        organization only lets admins create repos.
#   --recording TAG      the recording release to fetch. Default recording-rev30.
#   --recording-from DIR take the recording's .tar files from DIR instead of
#                        downloading them (for machines without internet).
#   --no-recording       skip the recording.
#   --no-venv            skip the Python environment and the test run.
#   --kit-url URL|PATH   where to clone the kit from: a URL, or the path of a
#                        local clone or mirror. Default the public kit on github.com.
#   --kit-repo O/N       the repo whose release holds the recording.
#                        Default edgy-solutions/openddil-starter-kit.
#   --kit-api URL        that repo's API base. Default https://api.github.com.
#   --connect-timeout SECS
#                        how long to wait for a connection to a host before
#                        stopping with a message that names it. A positive whole
#                        number. Default 20.
#   --offline            build the local checkout only: no network, no token, no
#                        GitHub repo, no origin remote, no push. Needs --kit-url
#                        (a local clone or mirror) and --recording-from DIR or
#                        --no-recording; not with --use-existing. Every push is
#                        refused until you list a remote in .git/info/allowed-remotes.
#
# The token:
#   GITHUB_TOKEN, else GH_TOKEN, else the one git's credential helper holds
#   for HOST. That is the same sign-in `git push` already uses; Git for
#   Windows' credential manager opens a browser sign-in if it has none.
#   It needs to be able to create a repo for OWNER, and push to it:
#     - classic token: the `repo` scope (and SSO authorized, if your org uses SSO);
#     - fine-grained token: resource owner OWNER, with "Administration" and
#       "Contents" read and write.
#   The token is never printed, and never put on a command line or in
#   .git/config.
#
# Set PYTHON to choose the interpreter. Otherwise it tries python3, python,
# then `py -3`.
#
# What you get:
#   - the kit's history on your private repo's main branch, remote `origin`;
#   - the public kit as remote `upstream`, which can be fetched from but never
#     pushed to (its push URL is DISABLED);
#   - the kit's git hooks installed in private mode, with only your private
#     repo listed in .git/info/allowed-remotes. Any push to another remote is
#     refused.
#   - data/ fetched and checked against SHA256SUMS. data/ is in .gitignore and
#     never committed.
#   - .venv with requirements.txt installed, and the template's tests run once.
#   With --offline, none of the GitHub parts: no origin, no push, and no pip.

set -Eeuo pipefail

DEFAULT_KIT_URL="https://github.com/edgy-solutions/openddil-starter-kit.git"
KIT_URL=$DEFAULT_KIT_URL
KIT_REPO="edgy-solutions/openddil-starter-kit"
KIT_API="https://api.github.com"
UA="openddil-new-algo-repo"

host=github.com
api=
dir=
description="Algorithm work, started from the OpenDDIL starter kit"
use_existing=0
connect_timeout=20
offline=0
recording=recording-rev30
recording_from=
want_recording=1
want_venv=1
target=

usage() {
  sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 2
}
die() { echo "new-algo-repo: $*" >&2; exit 1; }
need_arg() { [ "$1" -ge 2 ] || usage; }

while [ $# -gt 0 ]; do
  case "$1" in
    --host) need_arg $#; host=$2; shift 2 ;;
    --api-url) need_arg $#; api=$2; shift 2 ;;
    --dir) need_arg $#; dir=$2; shift 2 ;;
    --description) need_arg $#; description=$2; shift 2 ;;
    --use-existing) use_existing=1; shift ;;
    --recording) need_arg $#; recording=$2; shift 2 ;;
    --recording-from) need_arg $#; recording_from=$2; shift 2 ;;
    --no-recording) want_recording=0; shift ;;
    --no-venv) want_venv=0; shift ;;
    --kit-url) need_arg $#; KIT_URL=$2; shift 2 ;;
    --kit-repo) need_arg $#; KIT_REPO=$2; shift 2 ;;
    --kit-api) need_arg $#; KIT_API=$2; shift 2 ;;
    --connect-timeout) need_arg $#; connect_timeout=$2; shift 2 ;;
    --offline) offline=1; shift ;;
    -h|--help) usage ;;
    -*) echo "new-algo-repo: unknown option: $1" >&2; usage ;;
    *) [ -z "$target" ] || usage; target=$1; shift ;;
  esac
done

[ -n "$target" ] || usage
printf '%s' "$connect_timeout" | grep -Eq '^[1-9][0-9]*$' \
  || { echo "new-algo-repo: --connect-timeout wants a positive whole number of seconds, got '$connect_timeout'" >&2; usage; }

# The local directory a --kit-url names (a path or a file:// URI), or nothing.
local_kit_dir() {
  local p=$1
  case "$p" in file://*) p=${p#file://} ;; esac
  case "$p" in /[A-Za-z]:/*) p=${p#/} ;; esac
  if [ -d "$p" ]; then printf '%s' "$p"; fi
  return 0
}
if [ "$offline" = 1 ]; then
  [ "$use_existing" = 0 ] || die "--offline makes no repository, so there is nothing for --use-existing to use"
  [ "$KIT_URL" != "$DEFAULT_KIT_URL" ] || die "--offline needs --kit-url, the path of a local clone or mirror of the kit"
  [ -n "$(local_kit_dir "$KIT_URL")" ] || die "--offline needs --kit-url to be an existing local directory (a path or a file:// URI), got '$KIT_URL'"
  { [ -n "$recording_from" ] || [ "$want_recording" = 0 ]; } \
    || die "--offline needs --recording-from DIR (the recording's .tar files) or --no-recording"
fi
case "$target" in
  */*/*|/*|*/) die "OWNER/NAME expected, got '$target'" ;;
  */*) ;;
  *) die "OWNER/NAME expected, got '$target'" ;;
esac
owner=${target%%/*}
name=${target#*/}
printf '%s' "$owner" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9-]*$' || die "'$owner' isn't a valid owner name"
printf '%s' "$name" | grep -Eq '^[A-Za-z0-9._-]+$' || die "'$name' isn't a valid repo name"
[ -n "$dir" ] || dir=$name
api=${api%/}
if [ -z "$api" ]; then
  if [ "$host" = github.com ]; then api=https://api.github.com; else api="https://$host/api/v3"; fi
fi
KIT_API=${KIT_API%/}

# ---- tools -----------------------------------------------------------------
needed="git curl tar"
[ "$offline" = 0 ] || needed="git tar"
for tool in $needed; do
  command -v "$tool" >/dev/null 2>&1 || die "missing tool: $tool"
done
if command -v sha256sum >/dev/null 2>&1; then SUMCHECK=(sha256sum -c --quiet)
elif command -v shasum >/dev/null 2>&1; then SUMCHECK=(shasum -a 256 -c --quiet)
else die "missing tool: sha256sum (or shasum)"
fi

PY=()
if [ -n "${PYTHON:-}" ]; then
  PY=("$PYTHON")
else
  for cand in python3 python "py -3"; do
    # shellcheck disable=SC2086
    if command -v ${cand%% *} >/dev/null 2>&1 && $cand -c 'import sys' >/dev/null 2>&1; then
      read -r -a PY <<< "$cand"; break
    fi
  done
fi
[ ${#PY[@]} -gt 0 ] || die "no python found; install Python 3.11+ or set PYTHON"
"${PY[@]}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || die "python 3.11+ needed; ${PY[*]} is $("${PY[@]}" -c 'import sys; print(sys.version.split()[0])')"

if [ -e "$dir" ]; then die "'$dir' already exists here; choose another --dir or move it"; fi

# Native paths for the Windows builds of python and curl under Git Bash.
native() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }

WORK=$(mktemp -d)
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

step=""
on_err() {
  local rc=$?
  [ -n "$step" ] && echo "new-algo-repo: stopped at: $step" >&2
  exit "$rc"
}
trap on_err ERR

# json FILE KEY: one top-level field of a JSON object; booleans as true/false.
json() {
  "${PY[@]}" - "$(native "$1")" "$2" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    sys.exit(0)
v = d.get(sys.argv[2]) if isinstance(d, dict) else None
print("" if v is None else (str(v).lower() if isinstance(v, bool) else v))
PY
}

# ---- reaching a host -----------------------------------------------------------
# curl's exits for "couldn't connect": 6 host not found, 7 refused, 28 timed out, 35 TLS.
is_connect_rc() { case "$1" in 6|7|28|35) return 0 ;; esac; return 1; }
# connect_fail RC URL: stop at once with one line naming the host, the timeout and the cause.
connect_fail() {
  local rc=$1 url=$2 hp cause
  hp=${url#*://}; hp=${hp%%/*}; hp=${hp##*@}
  case "$rc" in
    6) cause="host not found" ;;
    7) cause="connection refused" ;;
    28) cause="timed out" ;;
    *) cause="TLS handshake failed" ;;
  esac
  die "can't reach $hp within $connect_timeout s ($cause). Check the host name, your network or proxy (HTTPS_PROXY), or use --offline."
}
# probe URL: git has no connect timeout for http, so reach the host with curl first.
# Any HTTP status counts as reachable; only a failure to connect stops.
probe() {
  local rc=0
  curl -sS -I -o "$(native "$WORK/probe.out")" --connect-timeout "$connect_timeout" -A "$UA" "$1" 2>/dev/null || rc=$?
  if is_connect_rc "$rc"; then connect_fail "$rc" "$1"; fi
  return 0
}

# ---- the token ---------------------------------------------------------------
token=
token_from=env
if [ "$offline" = 0 ]; then
  step="find a token for $host"
  token=${GITHUB_TOKEN:-${GH_TOKEN:-}}
  if [ -z "$token" ]; then
    token_from=helper
    token=$(printf 'protocol=https\nhost=%s\n\n' "$host" | git credential fill 2>/dev/null \
              | sed -n 's/^password=//p' | head -n 1) || true
  fi
  [ -n "$token" ] || die "no token for $host: set GITHUB_TOKEN, or sign git in to $host (any git clone or push of a private repo there does it)"

  AUTH="$WORK/auth.hdr"
  ( umask 077; printf 'Authorization: Bearer %s\n' "$token" > "$AUTH" )
fi

# api METHOD URL [JSON-BODY] [AUTH]: writes the body to $WORK/resp.json, prints the status.
api_call() {
  local method=$1 url=$2 body=${3-} auth=${4-yes} code
  local args=(-sS --connect-timeout "$connect_timeout" -o "$(native "$WORK/resp.json")" -w '%{http_code}' -X "$method"
              -H 'Accept: application/vnd.github+json' -H 'X-GitHub-Api-Version: 2022-11-28' -A "$UA")
  [ "$auth" = yes ] && args+=(-H "@$(native "$AUTH")")
  [ -n "$body" ] && args+=(-H 'Content-Type: application/json' --data-binary "$body")
  # curl's exit can't pass out of $( ), so a failure to connect stops the script from in
  # here: the subshell exits non-zero and the caller's assignment trips set -e.
  local rc=0
  code=$(curl "${args[@]}" "$url" 2>"$WORK/curl.err") || rc=$?
  if is_connect_rc "$rc"; then connect_fail "$rc" "$url"; fi
  if [ "$rc" != 0 ]; then cat "$WORK/curl.err" >&2; code=000; fi
  printf '%s' "$code"
}
api_message() { json "$WORK/resp.json" message; }

# git with the token supplied by GIT_ASKPASS, not on a command line or in config.
ASKPASS="$WORK/askpass.sh"
cat > "$ASKPASS" <<'SH'
#!/bin/sh
case "$1" in
  Username*) printf '%s\n' x-access-token ;;
  *) printf '%s\n' "$NEW_ALGO_REPO_TOKEN" ;;
esac
SH
chmod 700 "$ASKPASS"
git_auth() {
  if [ "$token_from" = env ]; then
    NEW_ALGO_REPO_TOKEN=$token GIT_ASKPASS=$(native "$ASKPASS") GIT_TERMINAL_PROMPT=0 \
      git -c credential.helper= "$@"
  else
    git "$@"
  fi
}

# ---- 1. the private repo ------------------------------------------------------
clone_url=
html_url=
if [ "$offline" = 1 ]; then
  echo "== 1/6 sign-in skipped (--offline)"
  echo "== 2/6 private repo skipped (--offline)"
else
step="check the token against $api"
code=$(api_call GET "$api/user")
[ "$code" = 200 ] || die "the token was refused by $api (HTTP $code: $(api_message)); check its scopes and its host"
login=$(json "$WORK/resp.json" login)
echo "== 1/6 signed in to $host as $login"

repo_url="$api/repos/$owner/$name"
if [ "$use_existing" = 1 ]; then
  step="read the existing repo $target"
  code=$(api_call GET "$repo_url")
  [ "$code" = 200 ] || die "$target can't be read (HTTP $code: $(api_message))"
  echo "== 2/6 using the existing repo $target"
else
  step="create the private repo $target"
  body=$("${PY[@]}" -c 'import json,sys; print(json.dumps({"name": sys.argv[1], "description": sys.argv[2], "private": True, "has_wiki": False, "auto_init": False}))' "$name" "$description")
  owner_lc=$(printf '%s' "$owner" | tr '[:upper:]' '[:lower:]')
  login_lc=$(printf '%s' "$login" | tr '[:upper:]' '[:lower:]')
  if [ "$owner_lc" = "$login_lc" ]; then create_url="$api/user/repos"; else create_url="$api/orgs/$owner/repos"; fi
  code=$(api_call POST "$create_url" "$body")
  case "$code" in
    201) ;;
    422) die "$target wasn't created: $(api_message). If it already exists, is private and is empty, re-run with --use-existing" ;;
    404) die "$owner is neither $login nor an organization this token can create repos in (HTTP 404)" ;;
    403) die "not allowed to create repos in $owner (HTTP 403: $(api_message)). Ask an admin to create an empty private $target, then re-run with --use-existing" ;;
    *) die "$target wasn't created (HTTP $code: $(api_message))" ;;
  esac
  echo "== 2/6 created $target"
  code=$(api_call GET "$repo_url")
  [ "$code" = 200 ] || die "$target was created but can't be read back (HTTP $code); nothing was pushed"
fi

step="check that $target is private"
is_private=$(json "$WORK/resp.json" private)
visibility=$(json "$WORK/resp.json" visibility)
clone_url=$(json "$WORK/resp.json" clone_url)
html_url=$(json "$WORK/resp.json" html_url)
if [ "$is_private" != true ] || { [ -n "$visibility" ] && [ "$visibility" != private ]; }; then
  die "STOP: $target reads private=$is_private visibility=${visibility:-unset}, not private. Nothing was pushed. Make it private (or delete it), then re-run with --use-existing"
fi
[ -n "$clone_url" ] || die "$target has no clone_url in the API's answer"

if [ "$use_existing" = 1 ]; then
  step="check that $target is empty"
  heads=$(git_auth ls-remote --heads "$clone_url") || die "can't list $target's branches with this token"
  [ -z "$heads" ] || die "$target already has branches; --use-existing only seeds an empty repo"
fi
fi

# ---- 2. the kit ---------------------------------------------------------------
step="clone the kit from $KIT_URL"
echo "== 3/6 clone the kit into $dir"
case "$KIT_URL" in http://*|https://*) probe "$KIT_URL" ;; esac
if [ "$offline" = 1 ]; then clone_hint="fix the cause and re-run"
else clone_hint="$target exists and is empty: fix the cause, then re-run with --use-existing"; fi
git clone -q --origin upstream "$KIT_URL" "$dir" \
  || die "the kit couldn't be cloned from $KIT_URL. $clone_hint"
cd "$dir"
# The kit is fetch-only: your work must never be pushed to it.
git remote set-url --push upstream DISABLED
if [ "$offline" = 0 ]; then git remote add origin "$clone_url"; fi

step="install the kit's hooks in private mode"
if [ -f tools/hooks/install-hooks.sh ] && sh tools/hooks/install-hooks.sh --mode private . >/dev/null; then
  allowed=$(git rev-parse --git-path info/allowed-remotes)
  # Offline there is no origin: the list stays empty, so every push is refused.
  if [ "$offline" = 0 ]; then printf '%s\n' "$clone_url" >> "$allowed"; fi
  hooks=installed
else
  echo "new-algo-repo: warning: the hooks weren't installed (is core.hooksPath set?); only the DISABLED push URL guards the public kit" >&2
  hooks=absent
fi

if [ "$offline" = 1 ]; then
  echo "== 4/6 push skipped (--offline)"
else
  step="push main to $target"
  case "$clone_url" in http://*|https://*) probe "$clone_url" ;; esac
  branch=$(git symbolic-ref --short HEAD)
  git_auth push -q -u origin "$branch:main" \
    || die "the push to $target failed; it is still empty. Remove $dir, fix the cause, then re-run with --use-existing"
  echo "== 4/6 pushed $branch to $target (main)"
fi

# ---- 3. the recording ---------------------------------------------------------
fetch_recording() {
  local tars=() sums=SHA256SUMS t
  if [ -n "$recording_from" ]; then
    for t in "$recording_from"/*.tar; do
      if [ -e "$t" ]; then cp "$t" .; fi
    done
    if [ -f "$recording_from/SHA256SUMS" ]; then
      cp "$recording_from/SHA256SUMS" "$WORK/SHA256SUMS"; sums="$WORK/SHA256SUMS"
    fi
  else
    local kit_auth=no
    [ "$KIT_API" = "$api" ] && kit_auth=yes
    code=$(api_call GET "$KIT_API/repos/$KIT_REPO/releases/tags/$recording" "" "$kit_auth")
    [ "$code" = 200 ] || die "release $recording of $KIT_REPO can't be read (HTTP $code: $(api_message))"
    "${PY[@]}" - "$(native "$WORK/resp.json")" > "$WORK/assets.tsv" <<'PY'
import json, sys
for a in json.load(open(sys.argv[1], encoding="utf-8")).get("assets", []):
    print(f"{a['name']}\t{a['browser_download_url']}")
PY
    local aname aurl
    while IFS=$'\t' read -r aname aurl; do
      aurl=${aurl%$'\r'}
      case "$aname" in
        *.tar|SHA256SUMS) ;;
        *) continue ;;
      esac
      case "$aname" in */*|..*) die "unexpected asset name in the release" ;; esac
      echo "   downloading $aname"
      local dest=$aname
      if [ "$aname" = SHA256SUMS ]; then dest="$WORK/SHA256SUMS"; sums="$WORK/SHA256SUMS"; fi
      local cargs=(-fsSL --connect-timeout "$connect_timeout" --retry 3 -A "$UA" -o "$(native "$dest")")
      [ "$kit_auth" = yes ] && cargs+=(-H "@$(native "$AUTH")")
      local crc=0
      curl "${cargs[@]}" "$aurl" 2>"$WORK/curl.err" || crc=$?
      if is_connect_rc "$crc"; then connect_fail "$crc" "$aurl"; fi
      if [ "$crc" != 0 ]; then cat "$WORK/curl.err" >&2; die "download of $aname failed"; fi
    done < "$WORK/assets.tsv"
  fi
  for t in ./*.tar; do
    if [ -e "$t" ]; then tars+=("$t"); fi
  done
  [ ${#tars[@]} -gt 0 ] || die "no .tar files in recording $recording"
  for t in "${tars[@]}"; do tar -xf "$t"; done
  [ -f "$sums" ] || die "no SHA256SUMS to check the recording against"
  if [ "$sums" != SHA256SUMS ]; then cp "$sums" SHA256SUMS.recording; sums=SHA256SUMS.recording; fi
  if ! "${SUMCHECK[@]}" "$sums"; then
    die "STOP: the recording doesn't match $sums. Delete data/ and the .tar files and download again before trusting any replay"
  fi
  rm -f "${tars[@]}"
  if [ "$sums" = SHA256SUMS.recording ]; then rm -f SHA256SUMS.recording; fi
}

if [ "$want_recording" = 1 ]; then
  step="fetch and check recording $recording"
  echo "== 5/6 fetch the recording ($recording) and check it"
  git check-ignore -q data/ || die "data/ isn't ignored by this kit's .gitignore; stopping before the recording lands in the repo"
  fetch_recording
  echo "   recording checks out"
else
  echo "== 5/6 recording skipped (--no-recording)"
fi

# ---- 4. python ------------------------------------------------------------------
if [ "$want_venv" = 1 ]; then
  step="create .venv and install requirements.txt"
  echo "== 6/6 python environment and the template's tests"
  "${PY[@]}" -m venv .venv
  if [ -x .venv/Scripts/python.exe ]; then VPY=.venv/Scripts/python.exe; else VPY=.venv/bin/python; fi
  if [ "$offline" = 1 ]; then
    echo "   .venv is made, but pip needs an index: nothing is installed and no tests ran (--offline)."
    echo "   From a folder of wheels (WHEELS):"
    echo "     $VPY -m pip install --no-index --find-links WHEELS -r requirements.txt"
    echo "     $VPY -m pytest -q template/tests"
  else
    "$VPY" -m pip install -q --disable-pip-version-check -r requirements.txt
    step="run the template's tests"
    "$VPY" -m pytest -q template/tests
  fi
else
  echo "== 6/6 python environment skipped (--no-venv)"
fi

step=""
if [ "$offline" = 1 ]; then
  repo_line="none (--offline)"
  hooks_line="$hooks (private mode; no remote is allowed yet, so every push is refused)"
  next3="Publish later: on a machine that can reach your GitHub host, have an empty private repo
     made and run tools/new-algo-repo.sh --use-existing $target; it clones fresh and
     checks the repo reads private before it pushes."
else
  repo_line=${html_url:-$target}
  hooks_line="$hooks (private mode; only origin may be pushed to)"
  next3="Work on branches and open pull requests in $target."
fi
cat <<EOF

Done. Private repo: $repo_line
Local checkout:     $(pwd)
Hooks:              $hooks_line

Next:
  1. Read README.md ("Day one"), DATA.md and FIRST-PROBLEMS.md.
  2. Copy template/speed_watch to start a unit, and replay it:
       .venv/bin/python run_replay.py template/speed_watch data/edge-01 out/speed_watch-edge-01.json
     (Windows: .venv/Scripts/python.exe)
  3. $next3

To take later updates from the kit (merge, never rebase a pushed branch):
  git fetch upstream && git merge upstream/main
EOF
