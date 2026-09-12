# Running the IOC under systemd — and swapping drivers

Two IOCs on this host can drive the camera, and only one may run at a time:

| | ADTucsen (default, boots with the host) | ADAxisSXR40 (this module) |
|---|---|---|
| Unit | `ioc-xv4040.service` (installed in `/etc/systemd/system`, **enabled**) | `ioc-axissxr40.service` ([source here](ioc-axissxr40.service); installed in `/etc/systemd/system` on 2026-09-10, **not enabled**) |
| Startup file | `/usr/local/epics/iocs/xv4040/st.cmd` | `iocs/axisSXR40IOC/iocBoot/iocAxisSXR40/st.cmd` |
| Runs as | `daenglis` | `gabrielgazolla` |
| procServ console | `telnet localhost 20000` | `telnet localhost 20001` |
| Console log | `/var/log/epics/xv4040.log` | `/var/log/areadetector/axisSXR40.log` (directory created by systemd at start) |
| PV prefix / asyn port | `XV4040:` / `TUCSEN` | `XV4040:` / `TUCSEN` (since 2026-09-10) |
| Images | `XV4040:Pva1:Image` over pvAccess, port 5075 | same |

The ADAxisSXR40 unit is a line-for-line mirror of Damon English's `ioc-xv4040.service`
with only the paths, user, service name and console port changed, so operators who know
one know the other. Damon's is documented in `/usr/local/epics/README.md`.

## Why both cannot run together

- The TUCam SDK opens the camera exclusively; the second IOC fails at `TUCAM_Dev_Open`
  with `Error in claiming interface!`.
- Both bind pvAccess port 5075. A second server silently falls back to an ephemeral
  port and remote clients then see **two** servers for `XV4040:Pva1:Image` and may
  attach to the wrong one. `pvlist` should always show exactly one GUID.

Both our launchers run the same start guard, `ioc-axissxr40-guard.sh`: `start_epics.sh`
calls it directly, and the systemd unit calls it through `ioc-axissxr40-run.sh`. We use
that check rather than `Conflicts=ioc-xv4040.service`, which would make starting our
service silently stop Damon's. Which IOC owns the camera is an operator decision.

## Install (one-time, host-level — outside this module)

```bash
sudo cp /usr/local/epics/support/areaDetector/ADAxisSXR40/info/systemd/ioc-axissxr40.service /etc/systemd/system/
sudo systemctl daemon-reload
```

Do **not** `systemctl enable` it. `ioc-xv4040` is the boot-time default; this unit
exists so a swap is one command, not so both compete at boot.

## Swap to ADAxisSXR40

```bash
sudo systemctl stop  ioc-xv4040
sudo systemctl start ioc-axissxr40
systemctl status ioc-axissxr40 --no-pager
pvlist                                  # exactly one server
pvget -r 'field(dimension)' XV4040:Pva1:Image
```

## Swap back to ADTucsen

```bash
sudo systemctl stop  ioc-axissxr40
sudo systemctl start ioc-xv4040
```

`ioc-xv4040` also comes back by itself at the next host boot, because it is the enabled
unit and ours is not.

## Make ADAxisSXR40 the boot-time default (only if that decision is taken)

```bash
sudo systemctl disable ioc-xv4040
sudo systemctl enable  ioc-axissxr40
```

and reverse the two lines to undo it. Nothing else changes.

## What is deliberately different from ioc-xv4040.service

| | ioc-xv4040 | ioc-axissxr40 | Why |
|---|---|---|---|
| procServ port | 20000 | 20001 | Both consoles can be listened on without clashing; nothing else about the ports differs |
| Log location | `/var/log/epics/xv4040.log` | `/var/log/areadetector/axisSXR40.log` via `LogsDirectory=areadetector` | `/var/log/epics` is owned by the xv4040 deployment and not writable by our user. `LogsDirectory=` makes systemd create `/var/log/areadetector` owned by our user at every start, with no manual `mkdir`/`chown`. The generic name leaves room for other areaDetector IOC logs, including his if it ever moves. Neither log is rotated yet; see below. |
| Guard against the other IOC | none | `ExecStart` is a launcher that runs [ioc-axissxr40-guard.sh](ioc-axissxr40-guard.sh) before procServ, see below | Damon's was written when it was the only IOC |
| `RestartPreventExitStatus=75` | — | set | A guard refusal must not be retried every 5 s by `Restart=always` |
| `After=` | `network-online.target` | `network-online.target ioc-xv4040.service` | If both were ever started in one boot, the guard runs after his has finished activating |
| `enable` state | enabled | not enabled | ioc-xv4040 stays the default |

Everything else — `Type`, `Restart=always`, `RestartSec=5`, `TimeoutStopSec=30`,
`KillSignal=SIGTERM`, the `--ignore=^C^D` and `--foreground --quiet` procServ flags,
and all seven `Environment=` lines for pvAccess and Channel Access — is identical.

## The start guard

The unit's `ExecStart` is [ioc-axissxr40-run.sh](ioc-axissxr40-run.sh), a launcher that
runs [ioc-axissxr40-guard.sh](ioc-axissxr40-guard.sh) and then `exec`s procServ. The
guard refuses to start the IOC when:

1. `ioc-xv4040.service` is `active` or `activating` (plain `is-active` misses the
   activating window at boot);
2. anything already listens on TCP 5075, the pvAccess server port — this catches Damon's
   IOC started by hand with `start.sh` instead of systemd, and any future third IOC.

It also warns, but does not refuse, if no Tucsen camera is on the USB bus.

A refusal exits 75 from the main process, and the unit's `RestartPreventExitStatus=75`
tells systemd this is a deliberate no-start, not a crash. The guard has to be in the main
process for that to work: `RestartPreventExitStatus=` does not apply to `ExecStartPre`, so
the first two versions of this guard, which ran there, were retried by `Restart=always`
every 5 s forever and `systemctl status` showed `activating (auto-restart)` (2026-09-10).

The reason is written to two places, because reading the system journal needs membership
of the `systemd-journal` group, which an operator account may not have:

```
$ sudo systemctl start ioc-axissxr40
Job for ioc-axissxr40.service failed because the control process exited with error code.

$ cat /var/log/areadetector/axisSXR40-guard.log        # no sudo needed
2026-09-10 16:34:15 REFUSING TO START: ioc-xv4040.service (ADTucsen) is active and holds the camera and PVA port 5075.
2026-09-10 16:34:15 Only one detector IOC may run. Stop it first:   sudo systemctl stop ioc-xv4040
2026-09-10 16:34:15 then:                                        sudo systemctl start ioc-axissxr40

$ sudo systemctl status ioc-axissxr40                   # same text, from the journal
```

The first line is systemd's and cannot be changed. After changing either script nothing
needs reinstalling (the unit calls the launcher by absolute path); after changing the unit
file, re-copy it and `daemon-reload`.

## First swap, verified 2026-09-10

`stop ioc-xv4040` then `start ioc-axissxr40`: start guard passed, `/var/log/areadetector/`
created by systemd, capability audit logged (11/15 capabilities, 8/12 properties), autosave
connected, `pvlist` showed exactly one server. `Manufacturer_RBV`, `PortName_RBV`, geometry
and `image1:NDArrayPort_RBV` read the same as under ioc-xv4040. 20 frames at 4096² reached
image1, Pva1 and Stats1 with zero drops; 10 frames streamed to HDF5 at 8.7 fps with
contiguous unique ids. Pool cap read back as 1907 MiB after poking `PoolMaxMem.PROC`.

Two things seen at that first boot, both expected:

- The old `auto_settings.sav` was keyed by `AXIS:SXR40:` names, so autosave logged one
  `dbFindRecord ... failed` per stale PV during restore and the IOC came up on template
  defaults. The next save cycle rewrote the file with `XV4040:` names; this does not recur.
- `caget` from a host with two interfaces warns `Identical process variable names on
  multiple servers`, naming 131.243.77.225 and 192.168.50.10. That is the *same* IOC seen
  on both of its addresses (one GUID in `pvlist`), not a second IOC. ioc-xv4040 behaves
  the same way.

Third start the same day, after fixing the calc request path (`$(CALC)/calcApp/Db`,
where `sseq_settings.req` actually lives) and removing macro text from the comments in
`auto_settings.req`: a clean log. Autosave connected 2270 of 2270 PVs; the only driver
messages are the 8 write errors for controls this camera does not implement and the
`GainMode` enum lookup, plus the SDK's own CameraLink probe lines (`OpenPhxCore`), which
appear in ioc-xv4040's log too. That is the expected baseline for every boot.

Autosave count, 2026-09-11: the boots above reported `2270 of 2270 PV's connected`
against `2391` on ioc-xv4040. The gap was a stale `commonPlugin_settings.req` in our
`iocBoot/` directory, tracked since the first release, which autosave's `./` search path
picked over ADCore's current one; it predated the Codec, BadPixel and Proc1 TIFF plugins,
so those 104 settings were silently never saved or restored on our IOC. The file was
removed so ADCore's applies, and a duplicate `BitDepth` line in `axisSXR40_settings.req`
(inherited from ADTucsen) was dropped. Expected from the next boot: `2373 of 2373` —
his 2354 unique PVs plus our 19 `image1:` settings that he does not save. His `2391`
counts the ADBase settings twice because his `auto_settings.req` includes that file
twice; the true unique count on his side is 2354.

## Logs

```bash
tail -f /var/log/areadetector/axisSXR40.log     # this IOC (only when started by systemd)
tail -f /var/log/epics/xv4040.log               # Damon's IOC
journalctl -u ioc-axissxr40 -f                  # service-level events only (starts, restarts)
```

The console log exists only when the IOC runs under the systemd unit: `start_epics.sh`
runs the IOC in the foreground with no procServ and no file, same as before. A crash's
last words are in the console log; the journal records only that a restart happened.

Neither log is rotated. A `logrotate` rule for `/var/log/areadetector/*.log` is the
obvious follow-up once there is a second IOC writing there; his file grew to under 1 MB
in a month, so this is tidiness rather than urgency.

## Operating notes (apply to both)

- Stop with `systemctl stop`, never `pkill`. Both `st.cmd` files start with a shebang,
  so the process name is `st.cmd`, not `tucsenApp`/`axisSXR40App`, and a `pkill -x`
  on the binary name silently does nothing while the old IOC keeps holding port 5075.
- `--ignore=^C^D` stops a stray Ctrl-C or Ctrl-D typed on the telnet console from
  killing the IOC. Detach from the console with `Ctrl-]` then `quit`.
- `Restart=always` brings a crashed IOC back after 5 s. The console log is where a
  crash's last words are; the journal only records the restart.
- After a swap, check `XV4040:cam1:SizeX_RBV` / `SizeY_RBV`. Each IOC has its own
  `autosave/` directory, so an ROI left small by a test under one driver is restored
  by that driver's autosave, not the other's. As of 2026-09-10 the xv4040 autosave
  holds `SizeY = 32` from the August frame-rate sweep.
