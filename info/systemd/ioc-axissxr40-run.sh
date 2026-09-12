#!/bin/sh
# ioc-axissxr40-run.sh -- ExecStart for ioc-axissxr40.service.
#
# Runs the start guard, then becomes procServ. The guard has to run HERE, as the main
# process, rather than in ExecStartPre: systemd's RestartPreventExitStatus= applies only
# to the main process, so a refusal from ExecStartPre was retried by Restart=always
# every 5 s forever. Here a refusal exits 75, the unit lists 75 in
# RestartPreventExitStatus=, and the service simply ends up "failed" with the reason in
# the journal and in /var/log/areadetector/axisSXR40-guard.log.
#
# The procServ command line is the one ioc-xv4040.service uses, with our paths and
# console port 20001 (his is 20000).
HERE=$(dirname "$0")
"$HERE/ioc-axissxr40-guard.sh" || exit $?

IOC=/usr/local/epics/support/areaDetector/ADAxisSXR40/iocs/axisSXR40IOC/iocBoot/iocAxisSXR40
LOG="${LOGS_DIRECTORY:-/var/log/areadetector}/axisSXR40.log"
exec /usr/bin/procServ --foreground --quiet \
    --ignore=^C^D \
    --logfile="$LOG" \
    --name=axissxr40 \
    20001 "$IOC/st.cmd"
