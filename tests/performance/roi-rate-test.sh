#!/bin/bash
# roi-rate-test.sh -- measure AXIS-SXR-40 frame rate at one ROI height,
#                     with or without HDF5 streaming to disk.
#
# Usage:  ./roi-rate-test.sh <height> <frames> [write|nowrite] [outdir]
#
#   height   ROI height in rows (width is always 4096). 4096 2048 1024 512 256
#            128 64 32 8 are the vendor's tabulated points.
#   frames   how many frames to time over. Pick enough that file open/close is
#            amortised -- see NOTE 3 below.
#   mode     "write"   acquire + NDFileHDF5 stream to disk (default)
#            "nowrite" acquire only, ArrayCallbacks disabled
#   outdir   where to stream files (default /home/$USER/axis-perf-tmp).
#            MUST be real storage -- see NOTE 4.
#
# Prints one result row. See README.md in this directory for the whole method.
#
# Requires: the IOC already running, and caget/caput on PATH.
set -u

H=${1:?height required}
N=${2:?frame count required}
MODE=${3:-write}
OUT=${4:-/home/$USER/axis-perf-tmp}

P=${AXIS_PREFIX:-AXIS:SXR40:}

# The detector IOC runs on THIS machine, so localhost has to be in the CA search
# path. A site environment normally points EPICS_CA_ADDR_LIST at a gateway -- here
# cagw-bldmz.als.lbl.gov, which serves accelerator PVs -- and that is legitimate and
# must not be discarded. Prepend rather than replace, so both resolve: the local
# detector and whatever the site setting provides.
export EPICS_CA_ADDR_LIST="127.0.0.1${EPICS_CA_ADDR_LIST:+ $EPICS_CA_ADDR_LIST}"
export EPICS_CA_AUTO_ADDR_LIST=NO

cput() { caput -w 5 -t "$@" >/dev/null 2>&1; }
cget() { caget -w 5 -t "$1" 2>/dev/null; }

# After any Acquire=0, confirm the driver actually returned to idle. If it did
# not, TUCAM_Cap_Stop has hung inside the SDK while the asyn port thread holds
# the port lock (seen after acquiring at 32 and 8 rows): every later caput
# queues forever, and the first visible symptom would otherwise be the NEXT
# point failing with "SizeY did not take" -- which points at the wrong thing.
# See ../incidents/stop-deadlock.md. Returns 1 on deadlock; callers exit 2.
wait_idle() {
    for _ in $(seq 20); do
        [ "$(cget "${P}cam1:DetectorState_RBV")" != "Acquire" ] && break
        sleep 0.5
    done
    if [ "$(cget "${P}cam1:DetectorState_RBV")" = "Acquire" ]; then
        echo "  h=$H FAILED: driver did not return to idle after Acquire=0 -- stopCapture"
        echo "          deadlock (see info/incidents/stop-deadlock.md). The IOC must be killed and"
        echo "          the host rebooted; do not run further points."
        return 1
    fi
    # DetectorState alone is NOT proof of life: upstream ADTucsen marks Idle before
    # its port thread hangs in Cap_Stop (measured 2026-08-25 -- it passed this check
    # while deadlocked). Prove the port thread is processing writes with one that
    # must round-trip: reset ArrayCounter and require the readback to follow.
    # Harmless -- every point takes its own counter baseline.
    # Probe with a value that DIFFERS from the current readback, so this can never
    # pass vacuously. An earlier version skipped the probe when the counter was
    # already 0 -- and passed nine times in a row on a deadlocked IOC, because
    # nothing was acquiring so the counter stayed 0 (2026-08-25 13:49).
    local c0 probe; c0=$(cget "${P}cam1:ArrayCounter_RBV")
    if [ "${c0:-0}" = "0" ]; then probe=1; else probe=0; fi
    caput -w 5 -t "${P}cam1:ArrayCounter" $probe >/dev/null 2>&1
    for _ in $(seq 10); do
        if [ "$(cget "${P}cam1:ArrayCounter_RBV")" = "$probe" ]; then
            [ "$probe" = 1 ] && caput -w 5 -t "${P}cam1:ArrayCounter" 0 >/dev/null 2>&1
            return 0
        fi
        sleep 0.5
    done
    echo "  h=$H FAILED: the driver's port thread is no longer processing writes"
    echo "          (ArrayCounter reset never took) -- stopCapture deadlock, see"
    echo "          info/incidents/stop-deadlock.md. Kill the IOC and reboot; run no more points."
    return 1
}

# ---- pre-flight: is the camera actually there? --------------------------------
# Without this the first symptom is "SizeY did not take (got 0)", which sends you
# looking at the ROI logic when the real problem is that the detector never
# connected -- powered off, unplugged, or the IOC still starting.
STATE=$(caget -w 10 -t "${P}cam1:DetectorState_RBV" 2>/dev/null)
if [ -z "$STATE" ]; then
    echo "  FAILED: no response from ${P}cam1 -- is the IOC running, and is"
    echo "          EPICS_CA_ADDR_LIST right? (currently '$EPICS_CA_ADDR_LIST')"
    exit 1
fi
MAXX=$(caget -w 10 -t "${P}cam1:MaxSizeX_RBV" 2>/dev/null)
if [ "$STATE" = "Disconnected" ] || [ "${MAXX:-0}" -le 1 ]; then
    echo "  FAILED: detector not connected (state='$STATE', MaxSizeX=$MAXX)."
    echo "          The IOC is up but the camera is not: check it is powered and"
    echo "          on the USB bus (lsusb -d 5453:e41b), then restart the IOC."
    exit 1
fi

# ---- stop whatever is running -------------------------------------------------
cput "${P}cam1:Acquire" 0
cput "${P}HDF1:Capture" 0
sleep 1
wait_idle || exit 2

# ---- exposure short enough that it never limits the rate ----------------------
# At 3726 fps the frame period is 268 us, so anything above that would cap the
# result. 20.64 us (2 x the 10.32 us sensor row time) is safely below every point.
cput "${P}cam1:AcquireTime" 0.00002

# ---- geometry ----------------------------------------------------------------
# Offsets FIRST, then sizes: setting a size while a non-zero offset is in place
# clamps it against that offset and it never re-expands. See NOTE 2.
cput "${P}cam1:MinX" 0
cput "${P}cam1:MinY" 0
cput "${P}cam1:SizeX" 4096
caput -w 8 -t "${P}cam1:SizeY" "$H" >/dev/null 2>&1
for _ in $(seq 20); do
    [ "$(cget "${P}cam1:SizeY_RBV")" = "$H" ] && break
    sleep 0.5
done
if [ "$(cget "${P}cam1:SizeY_RBV")" != "$H" ]; then
    echo "  h=$H FAILED: SizeY did not take (got $(cget "${P}cam1:SizeY_RBV"))"; exit 1
fi

if [ "$MODE" = "nowrite" ]; then
    # ---- acquire only: take plugins out of the picture entirely --------------
    cput "${P}cam1:ArrayCallbacks" 0
    cput "${P}cam1:ImageMode" 2                       # continuous
    C0=$(cget "${P}cam1:ArrayCounter_RBV")
    T0=$(date +%s.%N)
    caput -w 3 -c -t "${P}cam1:Acquire" 1 >/dev/null 2>&1
    sleep 1                                            # let it reach steady state
    C0=$(cget "${P}cam1:ArrayCounter_RBV"); T0=$(date +%s.%N)
    sleep 4
    C1=$(cget "${P}cam1:ArrayCounter_RBV"); T1=$(date +%s.%N)
    cput "${P}cam1:Acquire" 0
    python3 -c "
d=$C1-$C0; dt=$T1-$T0
print(f'  h=$H  acquire-only  {d/dt:9.1f} fps  {d*4096*$H*2/dt/1e6:6.0f} MB/s  ({d} frames / {dt:.2f} s)')"
    if [ "$((C1-C0))" -le 0 ]; then
        echo "  h=$H FAILED: acquisition produced NO frames -- camera or driver dead (see"
        echo "          info/incidents/stop-deadlock.md). Run no more points."
        exit 4
    fi
    wait_idle || exit 2
    exit 0
fi

# ---- acquire + write ----------------------------------------------------------
mkdir -p "$OUT"
cput "${P}cam1:ArrayCallbacks" 1
caput -w 5 -S "${P}HDF1:FilePath" "$OUT" >/dev/null 2>&1
cput "${P}HDF1:EnableCallbacks" 1
cput "${P}HDF1:FileWriteMode" 2                        # Stream: many frames, one file
cput "${P}HDF1:Compression" 0
caput -w 5 -S "${P}HDF1:FileTemplate" '%s%s_%3.3d.h5' >/dev/null 2>&1

# PRIME. NDFileHDF5 in Stream mode fixes the dataset geometry when Capture starts,
# from the dimensions of the LAST array it saw -- not the current ROI. Without a
# frame at the new geometry first, every frame is rejected with
# "Invalid frame. Ignoring.", NumCaptured stays 0 and you get a ~100 byte file with
# no error from the detector. See NOTE 1.
cput "${P}cam1:ImageMode" 0                            # single
# Require the frame COUNTER to advance, not just ArraySizeY_RBV == H. The
# readback can already be true from a previous point, so on its own it lets a
# dead driver "pass" the prime and the capture then fails downstream with
# "must collect an array to get dimensions first". Seen 2026-08-25.
AY=""; AC0=$(cget "${P}cam1:ArrayCounter_RBV")
for try in 1 2 3; do
    caput -w 20 -t "${P}cam1:Acquire" 1 >/dev/null 2>&1
    for _ in $(seq 10); do
        AY=$(cget "${P}cam1:ArraySizeY_RBV")
        [ "$AY" = "$H" ] && [ "$(cget "${P}cam1:ArrayCounter_RBV")" != "$AC0" ] && break
        sleep 0.5
    done
    [ "$AY" = "$H" ] && [ "$(cget "${P}cam1:ArrayCounter_RBV")" != "$AC0" ] && break
done
if [ "$AY" != "$H" ] || [ "$(cget "${P}cam1:ArrayCounter_RBV")" = "$AC0" ]; then
    echo "  h=$H FAILED: prime did not produce a NEW frame (ArraySizeY=$AY, counter unchanged)"; exit 1
fi

caput -w 5 -S "${P}HDF1:FileName" "perf$H" >/dev/null 2>&1
cput "${P}HDF1:NumCapture" "$N"
cput "${P}HDF1:DroppedArrays" 0                    # per-run figure; the counter is otherwise cumulative
# Acquire exactly N frames (Multiple mode) rather than running continuously and
# stopping after Capture reports Done. In continuous mode the camera keeps streaming
# for the ~0.5 s it takes the plugin to close a 1.7 GB file, those frames overflow
# the plugin queue, and DroppedArrays counts them -- although every one of the N
# frames is in the file. Measured 2026-08-26: all drops occurred AFTER written == N.
# With the camera stopping itself, DroppedArrays means what it says: frames lost.
cput "${P}cam1:ImageMode" 1                            # multiple
cput "${P}cam1:NumImages" "$N"
cput "${P}HDF1:Capture" 1

T0=$(date +%s.%N)
caput -w 3 -c -t "${P}cam1:Acquire" 1 >/dev/null 2>&1
# Wait for the capture to complete. If the camera has finished its N frames but
# NumCaptured is stuck short of N, do not sit here for 60 s: report the shortfall.
# (Seen once, 2026-08-26: 799 of 800 captured, 0 dropped, nothing logged; three
# instrumented repeats then gave 800/800/800. Unexplained one-off.)
STALL=0; LASTNC=-1
for _ in $(seq 240); do
    [ "$(cget "${P}HDF1:Capture_RBV")" = "Done" ] && break
    NC=$(cget "${P}HDF1:NumCaptured_RBV")
    if [ "$(cget "${P}cam1:DetectorState_RBV")" != "Acquire" ] && [ "$NC" = "$LASTNC" ]; then
        STALL=$((STALL+1)); [ $STALL -ge 12 ] && { echo "  h=$H WARNING: camera idle but capture stuck at $NC/$N -- giving up the wait"; break; }
    else STALL=0; fi
    LASTNC=$NC; sleep 0.25
done
T1=$(date +%s.%N)
cput "${P}cam1:Acquire" 0

NC=$(cget "${P}HDF1:NumCaptured_RBV")
DR=$(cget "${P}HDF1:DroppedArrays_RBV")
SZ=$(stat -c %s "$OUT/perf${H}_000.h5" 2>/dev/null || echo 0)
python3 -c "
nc=$NC; dt=$T1-$T0
print(f'  h=$H  +HDF5 write   {nc/dt:9.1f} fps  {nc*4096*$H*2/dt/1e6:6.0f} MB/s  '
      f'{nc}/$N frames  dropped=$DR  file={$SZ/1e6:.1f} MB')"
if [ "${NC:-0}" -le 0 ]; then
    echo "  h=$H FAILED: capture wrote NO frames -- camera or driver dead (see info/incidents/stop-deadlock.md)"
    exit 4
fi
wait_idle || exit 2
