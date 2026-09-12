#!/bin/bash
# run.sh -- run the ADAxisSXR40 functional test suite.
#
#   tests/run.sh [smoke|full|selftest|static|capture|build-h5check] [--prefix P] [--outdir DIR]
#                [--baseline FILE] [--driver auto|ours|adtucsen] [-- <extra pytest args>]
#   tests/run.sh stress [matrix|roi|compression|long|cycles|load|provoke|all ...]
#                [--stress-durations 10,25,50,100] [--stress-heights 4096,1024,256,32|all]
#                [--record] [--max-bytes GB] [--long-minutes N]
#
#   smoke     (default) everything not marked "full": ~3.5 min, no disk writes, no stress
#   full      adds file writes, robustness, workflow, performance regression and the compat comparison
#   stress    the sustained-load tier, by group. Bare "stress" = matrix roi compression (~7 min, ~30 GB
#             written, one file on disk at a time); "stress all" = every group but provoke (~16 min);
#             "stress provoke" runs the deliberately provoked writer-queue test. Files are checked and
#             deleted as they are produced; free space is checked before every run.
#   selftest  static/ + boot/ + pvs/test_inventory.py: proves the harness is wired, no camera writes
#   static    only tests that need no IOC (also what CI runs)
#   capture   dump every PV of the IOC that is serving into tests/compat/baselines/<driver>-<date>.json
#
# The suite never starts or stops an IOC. It detects which driver is serving XV4040:
# and applies that driver's expectations. Swapping drivers is the manual procedure in
# info/systemd/README.md.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
MODULE=$(cd "$HERE/.." && pwd)
EPICS_BIN=/usr/local/epics/base-7.0.10/bin/linux-x86_64
ADSUPPORT=/usr/local/epics/support/areaDetector/ADSupport

# Talk only to the local IOC. The host has two interfaces; pinning to loopback avoids
# "Identical process variable names on multiple servers" and a site gateway address list.
export EPICS_CA_ADDR_LIST=127.0.0.1 EPICS_CA_AUTO_ADDR_LIST=NO
export EPICS_CA_MAX_ARRAY_BYTES=40000000
# pvAccess stays on its defaults: the server answers broadcast searches, not unicast to loopback.
unset EPICS_PVA_ADDR_LIST EPICS_PVA_AUTO_ADDR_LIST
export PATH="$EPICS_BIN:$PATH"

MODE=smoke
[ $# -gt 0 ] && case "$1" in smoke|full|selftest|static|capture|build-h5check|stress) MODE=$1; shift;; esac

# stress groups -> test files; leading words that are group names are consumed here
STRESS_FILES=(); STRESS_EXTRA=()
if [ "$MODE" = stress ]; then
    while [ $# -gt 0 ]; do
        case "$1" in
            matrix)      STRESS_FILES+=(stress/test_stream_matrix.py) ;;
            roi)         STRESS_FILES+=(stress/test_roi_switching.py) ;;
            compression) STRESS_FILES+=(stress/test_compression_variants.py) ;;
            long)        STRESS_FILES+=(stress/test_long_continuous.py) ;;
            cycles)      STRESS_FILES+=(stress/test_capture_cycles.py) ;;
            load)        STRESS_FILES+=(stress/test_realistic_load.py) ;;
            provoke)     STRESS_FILES+=(stress/test_provoke_queue.py); STRESS_EXTRA+=(--provoke) ;;
            all)         STRESS_FILES+=(stress/test_stream_matrix.py stress/test_roi_switching.py stress/test_compression_variants.py
                                        stress/test_long_continuous.py stress/test_capture_cycles.py stress/test_realistic_load.py) ;;
            *) break ;;
        esac
        shift
    done
    [ ${#STRESS_FILES[@]} -eq 0 ] && STRESS_FILES=(stress/test_stream_matrix.py stress/test_roi_switching.py stress/test_compression_variants.py)
fi
# Drop a literal "--" anywhere: "tests/run.sh smoke -- -k roi" and "tests/run.sh smoke driver -- -q"
ARGS=(); for a in "$@"; do [ "$a" = "--" ] || ARGS+=("$a"); done; set -- "${ARGS[@]}"

# ---- venv: pytest on top of the system pyepics/numpy (Debian's pip is externally managed)
VENV="$HERE/.venv"
if [ ! -x "$VENV/bin/python" ]; then
    echo "creating $VENV (python3 -m venv --system-site-packages)"
    python3 -m venv --system-site-packages "$VENV"
fi
if ! "$VENV/bin/python" -c "import pytest" 2>/dev/null; then
    echo "installing pytest into $VENV"
    "$VENV/bin/pip" install -q pytest || { echo "pip failed; offline? run: $VENV/bin/pip install pytest" >&2; exit 3; }
fi
PY="$VENV/bin/python"
# p4p (pvAccess client) is optional: only stress/test_realistic_load.py's viewer needs it.
if [ "${MODE:-}" = "stress" ] && ! "$PY" -c "import p4p" 2>/dev/null; then
    echo "installing p4p into $VENV (optional; the viewer test skips without it)"
    "$VENV/bin/pip" install -q p4p || echo "p4p install failed; test_realistic_load will skip" >&2
fi

build_h5check() {
    local out="$HERE/.build/h5check" src="$MODULE/tools/h5check/h5check.c"
    mkdir -p "$HERE/.build"
    if [ ! -x "$out" ] || [ "$src" -nt "$out" ]; then
        echo "building h5check -> $out"
        gcc -O2 -o "$out" "$src" -I"$ADSUPPORT/include" -I"$ADSUPPORT/include/os/Linux" \
            -L"$ADSUPPORT/lib/linux-x86_64" -Wl,-rpath,"$ADSUPPORT/lib/linux-x86_64" \
            -lhdf5 -lhdf5_hl -lszip -lzlib -lm
    fi
}

cd "$HERE"
case "$MODE" in
    build-h5check) build_h5check ;;
    capture)       exec "$PY" compat/capture_baseline.py "$@" ;;
    static)        exec "$PY" -m pytest static "$@" ;;
    selftest)      exec "$PY" -m pytest static boot pvs/test_inventory.py "$@" ;;
    smoke)         exec "$PY" -m pytest -m "not full" --junitxml .results/smoke.xml "$@" ;;
    full)          build_h5check; exec "$PY" -m pytest --full --junitxml .results/full.xml "$@" ;;
    stress)        build_h5check; exec "$PY" -m pytest "${STRESS_FILES[@]}" --stress -m stress "${STRESS_EXTRA[@]}" \
                       --junitxml .results/stress.xml "$@" ;;
esac
