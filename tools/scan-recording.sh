#!/usr/bin/env bash
# Scan recording tarballs/directories for private terms, patterns, emails, person subjects and callsigns.
# Reports kinds and counts only, never a value. See scan_recording.py for the helpers.
set -eu
unset MSYS_NO_PATHCONV 2>/dev/null || true
# Some Git Bash builds abort on `grep -i -F` under the C locale, so probe for a locale where it runs.
# The data matched is ASCII only (non-printable bytes are masked), so the locale does not change matches.
for _l in C.UTF-8 en_US.UTF-8 C; do
  if echo t | LC_ALL=$_l grep -q -i -F -e T 2>/dev/null; then export LC_ALL=$_l; break; fi
done

HERE=$(cd "$(dirname "$0")" && pwd)
PY=${PYTHON:-python}
EMAIL_RE='[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'

usage() {
  echo "usage: tools/scan-recording.sh [--terms FILE]... [--patterns FILE]... [--work DIR] [--keep] INPUT..." >&2
  exit 1
}
die() { echo "scan-recording: $*" >&2; exit 1; }

TERMFILES=(); PATFILES=(); INPUTS=(); WORK=""; KEEP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --terms)    [ $# -ge 2 ] || usage; TERMFILES+=("$2"); shift 2 ;;
    --patterns) [ $# -ge 2 ] || usage; PATFILES+=("$2"); shift 2 ;;
    --work)     [ $# -ge 2 ] || usage; WORK=$2; shift 2 ;;
    --keep)     KEEP=1; shift ;;
    -h|--help)  usage ;;
    --)         shift; while [ $# -gt 0 ]; do INPUTS+=("$1"); shift; done ;;
    -*)         usage ;;
    *)          INPUTS+=("$1"); shift ;;
  esac
done
[ ${#INPUTS[@]} -gt 0 ] || usage
for f in ${TERMFILES[@]+"${TERMFILES[@]}"} ${PATFILES[@]+"${PATFILES[@]}"}; do
  [ -f "$f" ] || die "cannot read list file: $f"
done
for i in "${INPUTS[@]}"; do
  [ -e "$i" ] || die "no such input: $i"
done

if [ -n "$WORK" ]; then
  if [ -e "$WORK" ]; then
    [ -d "$WORK" ] || die "work path is not a directory: $WORK"
    [ -z "$(ls -A "$WORK")" ] || die "work dir is not empty: $WORK"
  else
    mkdir -p "$WORK"
  fi
else
  WORK=$(mktemp -d)
fi
cleanup() { [ "$KEEP" = 1 ] || rm -rf "$WORK"; }
trap cleanup EXIT

# Extract tarballs; directories are used in place.
SCAN=(); n=0
for i in "${INPUTS[@]}"; do
  if [ -d "$i" ]; then
    SCAN+=("$i")
  else
    n=$((n + 1)); mkdir -p "$WORK/in/$n"
    tar --force-local -xf "$i" -C "$WORK/in/$n" || die "cannot extract: $i"
    SCAN+=("$WORK/in/$n")
  fi
done

"$PY" "$HERE/scan_recording.py" dump --work "$WORK" "${SCAN[@]}" || die "dump failed"

# Per item: record numbers whose dump line matches, by grep's own matching.
: > "$WORK/results.tsv"; : > "$WORK/items.tsv"; : > "$WORK/hits-all.txt"
ITEMS=0
add_item() { # kind file line mode(F|E) text
  ITEMS=$((ITEMS + 1))
  local out="$WORK/hit.$ITEMS" rc=0
  if [ "$4" = F ]; then
    grep -n -i -F -e "$5" "$WORK/dump.txt" > "$out.raw" || rc=$?
  else
    grep -n -E -i -e "$5" "$WORK/dump.txt" > "$out.raw" || rc=$?
  fi
  [ "$rc" -le 1 ] || die "$1 $2 #$3 is not a valid expression"
  cut -d: -f1 "$out.raw" > "$out"; rm -f "$out.raw"
  printf '%s\t%s\t%s\t%s\t%s\n' "$ITEMS" "$1" "$2" "$3" "$4" >> "$WORK/items.tsv"
  cat "$out" >> "$WORK/hits-all.txt"
  # remember the text for pass 3 without ever printing it
  printf '%s' "$5" > "$WORK/item.$ITEMS.txt"
}
read_list() { # kind mode file
  local line t k=0
  while IFS= read -r line || [ -n "$line" ]; do
    k=$((k + 1)); line=${line%$'\r'}
    t=${line#"${line%%[![:space:]]*}"}; t=${t%"${t##*[![:space:]]}"}
    case "$t" in ''|'#'*) continue ;; esac
    add_item "$1" "$3" "$k" "$2" "$t"
  done < "$3"
}
for f in ${TERMFILES[@]+"${TERMFILES[@]}"}; do read_list terms F "$f"; done
for f in ${PATFILES[@]+"${PATFILES[@]}"}; do read_list pattern E "$f"; done
add_item email - 0 E "$EMAIL_RE"

sort -un "$WORK/hits-all.txt" > "$WORK/hits-union.txt"
"$PY" "$HERE/scan_recording.py" leaves --work "$WORK" "${SCAN[@]}" || die "leaves failed"

: > "$WORK/fieldhits.tsv"
while IFS=$'\t' read -r id kind file line mode; do
  hits="$WORK/hit.$id"
  nrec=$(wc -l < "$hits" | tr -d ' ')
  infield=0; raw=0; mn=0; mx=0
  if [ "$nrec" -gt 0 ]; then
    txt=$(cat "$WORK/item.$id.txt")
    rc=0
    if [ "$mode" = F ]; then
      grep -n -i -F -e "$txt" "$WORK/leaves-values.txt" | cut -d: -f1 > "$WORK/lv.$id" || rc=$?
    else
      grep -n -i -E -e "$txt" "$WORK/leaves-values.txt" | cut -d: -f1 > "$WORK/lv.$id" || rc=$?
    fi
    # leaf line -> (record, masked path), restricted to this item's hit records
    awk -F'\t' 'FILENAME==ARGV[1]{h[$1]=1;next} FILENAME==ARGV[2]{w[$1]=1;next} (FNR in w)&&($1 in h){print $1"\t"$3}' \
      "$hits" "$WORK/lv.$id" "$WORK/leaves-meta.tsv" | sort -u > "$WORK/fh.$id"
    cut -f1 "$WORK/fh.$id" | sort -u > "$WORK/fr.$id"
    infield=$(wc -l < "$WORK/fr.$id" | tr -d ' ')
    awk -v id="$id" -F'\t' '{print id"\t"$1"\t"$2}' "$WORK/fh.$id" >> "$WORK/fieldhits.tsv"
    raw=$((nrec - infield))
    if [ "$raw" -gt 0 ]; then
      awk 'FILENAME==ARGV[1]{f[$1]=1;next} !($1 in f)' "$WORK/fr.$id" "$hits" > "$WORK/rawrecs.$id"
      awk 'NR==FNR{w[$1]=1;next} (FNR in w)' "$WORK/rawrecs.$id" "$WORK/dump.txt" > "$WORK/rawlines.$id"
      if [ "$mode" = F ]; then
        grep -o -i -F -e "$txt" "$WORK/rawlines.$id" || true
      else
        grep -o -i -E -e "$txt" "$WORK/rawlines.$id" || true
      fi | awk '{l=length($0); if(mn==""||l<mn)mn=l; if(l>mx)mx=l} END{print mn+0, mx+0}' > "$WORK/len.$id"
      read -r mn mx < "$WORK/len.$id"
    fi
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$kind" "$file" "$line" "$nrec" "$infield" "$raw" "$mn-$mx" >> "$WORK/results.tsv"
done < "$WORK/items.tsv"

rc=0
"$PY" "$HERE/scan_recording.py" report --work "$WORK" || rc=$?
exit "$rc"
