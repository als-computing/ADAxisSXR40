#!/bin/sh
# ioc-axissxr40-health.sh -- is the ADAxisSXR40 IOC actually talking to the detector?
#
# systemd only knows whether the IOC *process* is alive; on 2026-09-14 ioc-xv4040 was
# "active" for two days with the camera powered off and, once the camera came back, stayed
# in DetectorState=Error with a dead SDK handle until somebody restarted it. This script is
# the one-minute check that ioc-axissxr40-run.sh (the unit's ExecStart) feeds to systemd as
# the unit's Status: line and as its watchdog heartbeat. It never runs on a schedule while
# ioc-xv4040 is serving: it lives inside our own service process and dies with it.
#
# Usage (by hand, as any user):   ioc-axissxr40-health.sh [PREFIX]      (default XV4040:)
# Prints ONE line and exits with the code:
#   0  OK:             camera on USB, detector state not Error/Disconnected, driver poll fresh
#   2  CAMERA ABSENT:  no Tucsen device (USB 5453:e41b) on the bus -- a restart cannot help
#   3  UNRESPONSIVE:   caget on DetectorState_RBV timed out (IOC hung, or still booting)
#   4  ERROR:          DetectorState is Error or Disconnected with the camera present
#   5  POLL FROZEN:    TemperatureActual's timestamp older than POLL_MAX_AGE_S with the camera
#                      present -- the driver's 0.5 s poll thread is stuck (stop-deadlock shape)
# The launcher sends the watchdog heartbeat for 0 and 2 only.
#
# Channel Access is pinned to this host, so the verdict is about the IOC on this machine and
# nothing else; both drivers serve the same prefix but only one runs at a time.
# AXIS_NO_TEMP_POLL set in the environment disables the driver's poll thread
# (axisSXR40.cpp), so the poll-age check is skipped when it is set.

PREFIX="${1:-XV4040:}"
EPICS_BASE_BIN="${EPICS_BASE_BIN:-/usr/local/epics/base-7.0.10/bin/linux-x86_64}"
CAGET="${CAGET:-$EPICS_BASE_BIN/caget}"
POLL_MAX_AGE_S="${POLL_MAX_AGE_S:-60}"
CA_TIMEOUT_S="${CA_TIMEOUT_S:-5}"
USB_ID="${USB_ID:-5453:e41b}"

export EPICS_CA_ADDR_LIST=127.0.0.1
export EPICS_CA_AUTO_ADDR_LIST=NO

now=$(date '+%H:%M:%S')

camera="camera present"
if command -v lsusb >/dev/null 2>&1; then
    if ! lsusb -d "$USB_ID" >/dev/null 2>&1; then
        echo "CAMERA ABSENT: no Tucsen device on USB ($USB_ID); waiting, no restart ($now)"
        exit 2
    fi
else
    camera="camera unknown (no lsusb)"
fi

if [ ! -x "$CAGET" ]; then
    echo "UNRESPONSIVE: caget not found at $CAGET ($now)"
    exit 3
fi

state=$("$CAGET" -t -w "$CA_TIMEOUT_S" "${PREFIX}cam1:DetectorState_RBV" 2>/dev/null)
if [ -z "$state" ]; then
    echo "UNRESPONSIVE: ${PREFIX}cam1:DetectorState_RBV did not answer within ${CA_TIMEOUT_S} s ($now)"
    exit 3
fi
# caget -t may still print a leading space; keep the first word.
state=$(echo "$state" | awk '{print $1}')

case "$state" in
  Error|Disconnected)
    echo "ERROR: DetectorState $state, $camera -- IOC needs a restart to re-open the camera ($now)"
    exit 4 ;;
esac

poll="poll disabled (AXIS_NO_TEMP_POLL)"
if [ -z "$AXIS_NO_TEMP_POLL" ]; then
    # caget -a prints:  <pv>  <YYYY-MM-DD> <HH:MM:SS.ffffff>  <value>
    stamp=$("$CAGET" -a -w "$CA_TIMEOUT_S" "${PREFIX}cam1:TemperatureActual" 2>/dev/null | awk '{print $2" "$3}')
    if [ -z "$stamp" ] || [ "$stamp" = " " ]; then
        echo "UNRESPONSIVE: ${PREFIX}cam1:TemperatureActual did not answer within ${CA_TIMEOUT_S} s ($now)"
        exit 3
    fi
    then_s=$(date -d "$stamp" '+%s' 2>/dev/null)
    now_s=$(date '+%s')
    if [ -z "$then_s" ]; then
        poll="poll age unknown (timestamp '$stamp')"
    else
        age=$((now_s - then_s))
        # An undefined timestamp (1990 epoch, never processed) shows as a huge age: frozen.
        if [ "$age" -gt "$POLL_MAX_AGE_S" ]; then
            echo "POLL FROZEN: DetectorState $state, $camera, temperature poll ${age} s old -- driver thread stuck ($now)"
            exit 5
        fi
        poll="poll ${age} s old"
    fi
fi

echo "OK: $state, $camera, $poll ($now)"
exit 0
