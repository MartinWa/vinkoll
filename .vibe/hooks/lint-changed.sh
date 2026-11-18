#!/usr/bin/env bash
# Vibe post_agent hook "lint-changed" for Vinkoll (Python / Django / ruff).
#
# Behavior:
#   - cd to the repo root, collect tracked-modified + untracked *.py files
#     (git diff --name-only HEAD + git ls-files --others --exclude-standard);
#     exit 0 silently when there are none.
#   - Run `ruff check` and `ruff format --check` on exactly those files, inside
#     the project's Linux dev container (compose.development.yaml) when it is
#     running -- the canonical environment per README.md and CI -- otherwise in
#     the pinned local .venv; exit 0 silently when neither runner is available
#     (e.g. Docker Desktop not running).
#   - ruff exit code 1 = findings -> print {"decision":"deny","reason":...} on
#     stdout so the agent fixes them before the turn finishes.
#   - Any other non-zero code, or a missing runner, is infrastructure failure:
#     exit 0 with no output (fail open; never block a turn on a tooling hiccup).

set -uo pipefail

cd "$(dirname "$0")/../.." || exit 0

compose_file=compose.development.yaml

# --- 1. Changed files of the project's language (Python) -------------------
mapfile -t candidates < <(
    { git diff --name-only HEAD; git ls-files --others --exclude-standard; } \
        | sort -u | grep '\.py$' || true
)

files=()
for f in "${candidates[@]}"; do
    [[ -f "$f" ]] && files+=("$f")
done
[[ ${#files[@]} -eq 0 ]] && exit 0

# --- 2. Pick a runner: dev container when up, else local .venv -------------
runner=()
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1 \
    && [[ -n "$(docker compose -f "$compose_file" ps -q --status running vinkoll 2>/dev/null)" ]]; then
    runner=(docker compose -f "$compose_file" exec -T vinkoll python -m ruff)
fi
if [[ ${#runner[@]} -eq 0 ]]; then
    for rf in .venv/Scripts/ruff.exe .venv/bin/ruff; do
        if [[ -x "$rf" ]]; then
            runner=("$rf")
            break
        fi
    done
fi
# No runner available: silent, fail open.
[[ ${#runner[@]} -eq 0 ]] && exit 0

# --- 3. Lint + format-check only those files --------------------------------
tmp_out="$(mktemp)"
trap 'rm -f "$tmp_out"' EXIT

findings=""
found=0

"${runner[@]}" check "${files[@]}" >"$tmp_out" 2>&1
rc=$?
if (( rc == 1 )); then
    found=1
    findings+="ruff check:
$(cat "$tmp_out")"
elif (( rc != 0 )); then
    exit 0 # infrastructure failure: fail open
fi

"${runner[@]}" format --check "${files[@]}" >"$tmp_out" 2>&1
rc=$?
if (( rc == 1 )); then
    found=1
    findings+="${findings:+
}ruff format --check:
$(cat "$tmp_out")"
elif (( rc != 0 )); then
    exit 0 # infrastructure failure: fail open
fi

[[ $found -eq 0 ]] && exit 0

# --- 4. Report findings as a structured deny, capped ------------------------
# Cap the full lint output before escaping (bytes; ~12000 keeps it readable).
printf -v findings '%.12000s' "$findings"

reason="${findings//$'\r'/}"
reason="${reason//\\/\\\\}"
reason="${reason//\"/\\\"}"
reason="${reason//$'\n'/\\n}"
reason="${reason//$'\t'/\\t}"

printf '{"decision":"deny","reason":"%s"}\n' "$reason"
exit 0
