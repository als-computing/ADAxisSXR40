#!/bin/sh
# ioc-axissxr40-guard.sh -- start guard for ioc-axissxr40.service.
#
# Refuses to let the ADAxisSXR40 IOC start while anything else could be holding the
# camera or the pvAccess server port, and says WHY in the journal, so that
#   sudo systemctl status ioc-axissxr40   or   cat /var/log/areadetector/axisSXR40-guard.log
# shows a sentence instead of "control process exited with error code".
#
# Called by ioc-axissxr40-run.sh (the unit's ExecStart), NOT from ExecStartPre:
# RestartPreventExitStatus= only applies to the main process, so a guard failing in
# ExecStartPre is retried by Restart=always every 5 s forever ("activating
# (auto-restart)") -- observed 2026-09-10 with the first two versions of this guard.
#
# Exit codes:
#   0   clear to start
#   75  refused (EX_TEMPFAIL). The launcher exits with this same code and the unit
#       lists 75 in RestartPreventExitStatus=, so a refusal is a final "failed", not a
#       restart loop.
#
# Checks, in order:
#   1. ioc-xv4040.service active OR activating. Plain "is-active" only reports the
#      fully-active state, which leaves a window at boot if both units were ever
#      enabled; "activating" closes it.
#   2. Anything listening on TCP 5075 (pvAccess). Catches Damon's IOC started by hand
#      with start.sh rather than systemd, and any future third IOC.
#   3. The Tucsen camera is not present on USB (informational: the IOC would start
#      and sit Disconnected; still allowed, but say so).

# Every line goes to stdout (the journal) AND to a guard log in the IOC log directory,
# because reading the system journal needs membership of the systemd-journal group,
# which an ordinary operator account may not have. LOGS_DIRECTORY is set by systemd
# from the unit's LogsDirectory=; the fallback is for running this by hand.
GLOG="${LOGS_DIRECTORY:-/var/log/areadetector}/axisSXR40-guard.log"
say() { echo "ioc-axissxr40: $*"; echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$GLOG" 2>/dev/null; }

st=$(systemctl is-active ioc-xv4040.service 2>/dev/null)
case "$st" in
  active|activating|reloading)
    say "REFUSING TO START: ioc-xv4040.service (ADTucsen) is $st and holds the camera and PVA port 5075."
    say "Only one detector IOC may run. Stop it first:   sudo systemctl stop ioc-xv4040"
    say "then:                                        sudo systemctl start ioc-axissxr40"
    exit 75 ;;
esac

if ss -Hltn 'sport = :5075' 2>/dev/null | grep -q . ; then
    owner=$(ss -Hltnp 'sport = :5075' 2>/dev/null | sed -n 's/.*users:(("\([^"]*\)",pid=\([0-9]*\).*/\1 (pid \2)/p' | head -1)
    say "REFUSING TO START: something is already serving pvAccess on TCP 5075${owner:+: $owner}."
    say "That is another detector IOC (ioc-xv4040 started by hand?). Stop it, then retry."
    exit 75
fi

if command -v lsusb >/dev/null 2>&1 && ! lsusb -d 5453:e41b >/dev/null 2>&1; then
    say "WARNING: no Tucsen camera (USB 5453:e41b) on the bus. Starting anyway; the IOC will come up Disconnected."
fi

say "clear to start (ioc-xv4040 is $st, port 5075 free)"
exit 0
