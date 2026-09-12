#!/bin/bash
# Start the ADAxisSXR40 IOC with the same network environment as ioc-xv4040.service,
# so the two IOCs are interchangeable for clients. Mirrors the Environment= lines of
# /etc/systemd/system/ioc-xv4040.service (Damon English, 2026-08).
#
# Refuses to start while ioc-xv4040 is running: the SDK opens the camera exclusively
# and both IOCs bind pvAccess port 5075. A second PVA server silently falls back to an
# ephemeral port and remote clients then see two servers for XV4040:Pva1:Image.
#
# Previous versions of this script set EPICS_CA_SERVER_PORT=5077 and launched medm.
# Both are gone: a non-default CA port made this IOC invisible to every client that
# found ioc-xv4040 on 5064, and the screen belongs to a separate launcher.
set -e
cd "$(dirname "$0")"

# Same start guard the systemd unit uses (info/systemd/ioc-axissxr40-guard.sh): refuses
# if ioc-xv4040 is active/activating or anything already serves pvAccess on 5075, and
# says why. Exit 75 on refusal.
"$(dirname "$0")/../../../../info/systemd/ioc-axissxr40-guard.sh" || exit $?

# pvAccess is the primary image transport. Bind every interface so clients on other
# VMs of this Proxmox host can reach the server; beacon on the beamline LAN and the
# host-internal bridge so PVA autodiscovery works without EPICS_PVA_ADDR_LIST.
export EPICS_PVAS_INTF_ADDR_LIST=0.0.0.0
export EPICS_PVAS_BEACON_ADDR_LIST="131.243.77.255 192.168.50.255"
export EPICS_PVA_AUTO_ADDR_LIST=YES
export EPICS_PVA_SERVER_PORT=5075
export EPICS_PVA_BROADCAST_PORT=5076
# Channel Access kept working for legacy clients; images should go over PVA.
export EPICS_CA_AUTO_ADDR_LIST=YES
export EPICS_CA_MAX_ARRAY_BYTES=40000000

# iocsh exits on stdin EOF, so keep stdin attached.
exec ../../bin/linux-x86_64/axisSXR40App st.cmd
