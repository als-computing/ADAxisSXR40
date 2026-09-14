#!/bin/sh
# tools/blueskyTest/run.sh -- run main.py (a bluesky scan against the live XV4040 IOC) in a
# venv that has bluesky, ophyd and h5py on top of the system pyepics/numpy.
#
#   tools/blueskyTest/run.sh                    # 5-point scan, file checked then deleted
#   tools/blueskyTest/run.sh --points 10 --keep
#
# Channel Access is pinned to this host, like tests/run.sh: both IOCs serve XV4040: and only
# the local one may answer. pvAccess is not used here.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
VENV="$HERE/.venv"
if [ ! -x "$VENV/bin/python" ]; then
    echo "creating $VENV (python3 -m venv --system-site-packages)"
    python3 -m venv --system-site-packages "$VENV"
fi
if ! "$VENV/bin/python" -c "import bluesky, ophyd, h5py" 2>/dev/null; then
    echo "installing bluesky ophyd h5py into $VENV"
    "$VENV/bin/pip" install -q bluesky ophyd h5py
fi
export EPICS_CA_ADDR_LIST=127.0.0.1 EPICS_CA_AUTO_ADDR_LIST=NO
export EPICS_CA_MAX_ARRAY_BYTES=40000000
unset EPICS_PVA_ADDR_LIST EPICS_PVA_AUTO_ADDR_LIST
cd "$HERE"
exec "$VENV/bin/python" main.py "$@"
