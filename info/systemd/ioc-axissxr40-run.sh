#!/bin/sh
# ioc-axissxr40-run.sh -- ExecStart for ioc-axissxr40.service (Type=notify).
#
# 1. Runs the start guard (ioc-axissxr40-guard.sh). A refusal exits 75 before anything is
#    told to systemd; the unit lists 75 in RestartPreventExitStatus=, so the service ends up
#    "failed" with the reason in the journal and in /var/log/areadetector/axisSXR40-guard.log
#    instead of restarting every 5 s. (Not ExecStartPre: RestartPreventExitStatus= applies
#    only to the main process; observed 2026-09-10.)
# 2. Starts procServ (same command line as ioc-xv4040.service, our paths, console 20001) in
#    the background and stays as the main process.
# 3. Waits for the IOC to answer Channel Access, then tells systemd READY=1: "active
#    (running)" now means the IOC is up, not merely that procServ was forked.
# 4. Every HEALTH_INTERVAL seconds runs ioc-axissxr40-health.sh and hands its one-line
#    verdict to systemd as the unit's Status: line ("systemctl status ioc-axissxr40").
#    The watchdog heartbeat (WATCHDOG=1) is sent only when the verdict is OK or CAMERA
#    ABSENT. For ERROR / UNRESPONSIVE / POLL FROZEN it is withheld; after WatchdogSec
#    without a heartbeat systemd stops the service (WatchdogSignal=SIGTERM) and
#    Restart=always brings it back, which re-opens the camera. StartLimitBurst= in the unit
#    caps that at a few restarts per half hour, after which the unit stays "failed" for a
#    person to look at.
# 5. State changes are appended to axisSXR40-health.log beside the IOC log, so the history
#    is readable without journal rights.
#
# Nothing here looks at, or acts on, ioc-xv4040: this process exists only while our unit
# runs, and systemd restarts only the unit that owns it.

HERE=$(dirname "$0")
"$HERE/ioc-axissxr40-guard.sh" || exit $?

IOC=/usr/local/epics/support/areaDetector/ADAxisSXR40/iocs/axisSXR40IOC/iocBoot/iocAxisSXR40
LOGDIR="${LOGS_DIRECTORY:-/var/log/areadetector}"
LOG="$LOGDIR/axisSXR40.log"
HLOG="$LOGDIR/axisSXR40-health.log"
HEALTH="$HERE/ioc-axissxr40-health.sh"
INTERVAL="${HEALTH_INTERVAL:-60}"
PREFIX="${IOC_PREFIX:-XV4040:}"
STARTUP_WAIT="${HEALTH_STARTUP_WAIT:-170}"      # < TimeoutStartSec in the unit

hlog() { echo "health: $*"; echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$HLOG" 2>/dev/null; }
notify() { command -v systemd-notify >/dev/null 2>&1 && [ -n "$NOTIFY_SOCKET" ] && systemd-notify "$@"; return 0; }

/usr/bin/procServ --foreground --quiet \
    --ignore=^C^D \
    --logfile="$LOG" \
    --name=axissxr40 \
    20001 "$IOC/st.cmd" &
PROCSERV=$!

# systemctl stop / the watchdog send SIGTERM here; pass it on and wait for procServ to end.
stopping=0
on_term() { stopping=1; hlog "stopping (signal received); forwarding to procServ pid $PROCSERV"; kill -TERM "$PROCSERV" 2>/dev/null; }
trap on_term TERM INT

# --- wait for the IOC to answer CA, then READY ------------------------------------------------
waited=0
verdict=""
while [ "$waited" -lt "$STARTUP_WAIT" ]; do
    kill -0 "$PROCSERV" 2>/dev/null || break
    verdict=$("$HEALTH" "$PREFIX"); rc=$?
    case "$rc" in
      3) notify --status="starting: $verdict"; sleep 5; waited=$((waited + 5)) ;;
      *) break ;;
    esac
done
if kill -0 "$PROCSERV" 2>/dev/null; then
    notify --ready --status="$verdict"
    hlog "READY -> $verdict"
fi
last="${verdict%%:*}"

# --- the loop ---------------------------------------------------------------------------------------
while kill -0 "$PROCSERV" 2>/dev/null && [ "$stopping" -eq 0 ]; do
    sleep "$INTERVAL" &
    wait $! 2>/dev/null                      # interruptible sleep (trap fires during wait)
    [ "$stopping" -eq 0 ] || break
    kill -0 "$PROCSERV" 2>/dev/null || break
    verdict=$("$HEALTH" "$PREFIX"); rc=$?
    kind="${verdict%%:*}"
    case "$rc" in
      0|2) notify --status="$verdict" WATCHDOG=1 ;;
      *)   notify --status="$verdict -- no heartbeat; systemd restarts the IOC after WatchdogSec without recovery" ;;
    esac
    if [ "$kind" != "$last" ]; then
        hlog "$last -> $verdict"
        last="$kind"
    fi
done

wait "$PROCSERV" 2>/dev/null
status=$?
hlog "procServ exited with status $status"
exit $status
