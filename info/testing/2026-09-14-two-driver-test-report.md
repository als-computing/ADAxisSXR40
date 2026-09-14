# Test report: ADAxisSXR40 and ADTucsen on the XV4040 detector — 2026-09-14

**Summary.** The complete suite, 345 tests in 12 categories, was run from a clean results
directory against both EPICS drivers for the Dhyana XV4040 detector on `bl1101ad01`, same
code, same day, one after the other: our ADAxisSXR40 (11:45 to 12:31) and Damon English's
ADTucsen `ioc-xv4040` (12:37 to 13:03). **Every test passes on both drivers.** The only
non-passes are 3 expected failures shared by both (items of the camera or of areaDetector,
not of either driver) and, on ADTucsen, the 6 tests that check the fixes this fork exists
for, which fail there by design. Nothing was left behind: no stray files, every setting
restored, zero new error lines in either IOC log during the runs.

This repeats the [2026-09-11 report](2026-09-11-two-driver-test-report.md) after a weekend
camera power-off, with the health line added to our systemd unit in between.

## Results by category

| Category | What it proves | Tests | ADAxisSXR40 | ADTucsen |
|---|---|---|---|---|
| static | template ↔ driver parameters, request files, startup and systemd files (unit keys, launcher, every verdict of the health script), documentation links; no IOC needed, runs in CI | 109 | 108 pass¹ | 109 pass |
| boot | last-boot console log: all PVs connected, exactly the expected write errors, no warnings; autosave file; one PVA server; start guard; our unit's health `Status:` line fresh and `OK:` | 24 | 23 pass, 1 skip² | 19 pass, 5 n/a³ |
| pvs | every record connects with the right type and enum strings; identity strings; every safe setpoint round-trips | 61 | 61 pass | 59 pass, 2 n/a³ |
| driver | ROI alignment, height clamp, AutoLevels→Histogram, frame-format bounds, exposure quantisation, ReverseY | 32 | 32 pass | 25 pass, 6 expected fail⁴, 1 n/a³ |
| acquire | Single / Multiple / Continuous, software trigger, exposure applied, plugins delivering, PVA image, CA vs PVA equality, pool cap, timestamps, writer error paths | 64 | 63 pass, 1 xfail⁵ | 61 pass, 1 xfail⁵, 2 n/a³ |
| image | real sensor data (not a test pattern), frames differ, dark level | 4 | 3 pass, 1 xfail⁶ | 3 pass, 1 xfail⁶ |
| files | HDF5 stream verified in-file (dims, dtype, chunking, unique ids, frame intervals), TIFF single | 7 | 6 pass, 1 xfail⁶ | 6 pass, 1 xfail⁶ |
| robustness | 20 start/stop cycles at 32 rows with the deadlock probe, binning, 5 s exposure, writes during acquisition, pool leak | 7 | 7 pass | 7 pass |
| workflow | the ophyd scan sequence (one file per scan, one per point) and the HDF5 file contract (dataset paths, NDAttributes) | 5 | 5 pass | 5 pass |
| performance | frame rate at every ROI height within 5 % of the recorded reference | 3 | 3 pass | 3 pass |
| compat | our 7533 PVs against the 7529 recorded from ADTucsen: only the 7 intended differences | 12 | 12 pass | is the baseline |
| stress | sustained load, own tier (below), plus the provoked queue overflow | 17 | 17 pass | 17 pass |
| **Total** | | **345** | **340 pass, 3 xfail, 1 skip** | **314 pass, 9 xfail, 22 n/a** |

¹ Our static run happened before today's stress record file existed; the 109th test is the link check of that file.
² The autosave-freshness check skips when the IOC has been up less than 5 minutes.
³ "n/a": tests of things that exist only in ADAxisSXR40 (its health line and start guard, its 4 extra records, its capability audit, the compat comparison) or of the environment (his IOC runs as another user).
⁴ The fork's fixes, absent upstream by definition: SizeY/MinY alignment to 4 (3 tests), AutoLevels publishing Histogram, RGB888 rejected on a mono sensor, ReverseY readback. Each is marked as expected to fail on ADTucsen with the reason; if his driver gained the fix the test would flag it.
⁵ Neither driver publishes the camera record's own timestamp/unique-id PVs (the plugins carry them). Known gap, same in both.
⁶ Hardware state, not software: the dark-frame mean reads ~1650 ADU where ~68 is expected; to be checked at the detector.

## Stress tier: both drivers under sustained load

Uncompressed HDF5 streaming with the full plugin chain on, every file checked with
`tools/h5check` (dimensions, data type, chunking, contiguous unique ids, frame intervals,
per-frame statistics) and deleted afterwards. 46 streaming runs and about 60 GB written per driver.

| Run | ADAxisSXR40 | ADTucsen |
|---|---|---|
| Full frame 4096 rows, 25 s | 210 frames, camera 8.6 fps, writer 8.38 fps, 281 MB/s, 0 drops, max frame gap 119 ms (nominal 116) | identical: 8.38 fps, 0 drops, max gap 119 ms |
| 256 rows, 25 s | 3148 frames, camera 137 fps, writer 134 fps, 280 MB/s, 0 drops | identical |
| 32 rows, 5 s | 4726 frames, 1037 fps camera, 943 fps writer, 0 drops | identical |
| ROI switching 4096 → 32 → 1024 → 4096 | clean at every step, deadlock probe passed after each stop | identical |
| 5 compressions (none, zlib, Blosc, Bitshuffle-LZ4, LZ4) | all complete and readable; Blosc/Bitshuffle 1.5×, zlib 1.34×, LZ4 1.0× | identical |
| 5 min continuous, plugins off | 8.6 fps at every 30 s sample, memory flat after the one-time 256 MB start-up allocation, telemetry updating | identical |
| 30 capture cycles at 1024 rows, 12.6 GB | 30 identical 419.5 MB files, FileNumber correct, memory flat | identical |
| 25 s full frame with a pvAccess viewer subscribed and statistics computing | 0 drops; the viewer received every frame (7.1 GB) | identical |
| Provoked overflow (writer queue 1, zlib 6, continuous) | frames dropped *at the plugin* and counted, IOC back to Idle, pool far under its cap | identical |

Full tables: [ADAxisSXR40](../performance/2026-09-14-stress-adaxissxr40-bl1101ad01.md),
[ADTucsen](../performance/2026-09-14-stress-adtucsen-bl1101ad01.md). The data path is the
SDK's and the disk's, so the two drivers are indistinguishable under load; the differences
between them are in control behaviour (the fork fixes) and in operations (below).

## Interchangeability and operations

- Same prefix `XV4040:`, same asyn port, same plugin chain. A client cannot tell the IOCs
  apart except by the 7 intended differences: 4 records only ADAxisSXR40 has (TEC enable,
  ring-buffer counters), RGB888 removed from the frame-format menu, and the sensor
  temperature published with the per-unit calibration and two decimals.
- Swap is `systemctl stop` one, `systemctl start` the other; done twice today without incident.
  ADTucsen remains the default at boot; the ADAxisSXR40 unit is installed but not enabled, and
  its start guard refuses to run while `ioc-xv4040` is active.
- **New since Friday.** After the weekend camera power-off both IOCs would sit `active` in
  `DetectorState=Error` until restarted by hand; systemd cannot see the camera. Our unit now
  runs a one-minute health check inside the service: `systemctl status ioc-axissxr40` shows
  `Status: "OK: Idle, camera present, poll 1 s old (12:31:29)"`, and when the camera is present
  but the IOC is in Error, hung, or its driver poll is frozen, the unit stops sending its watchdog
  heartbeat and systemd restarts it within about three minutes (three times per half hour at
  most). Verified live today: `active (running)` only once the IOC answered Channel Access,
  heartbeat received every minute, clean stop through the supervisor. `ioc-xv4040` is unchanged
  and still needs the manual restart. Details: [systemd/README.md](../systemd/README.md).

## What the suite is

`ADAxisSXR40/tests/`, pytest, `tests/run.sh smoke|full|static|stress`. The suite never starts
or stops a service, restores every setting it changes, refuses to write any PV outside an
allow-list, runs the deadlock probe after every acquisition stop, watches the IOC log for new
errors during the whole session, and deletes every file it writes after verifying it. The
static tier runs in CI on every push. Method and per-folder detail:
[tests/README.md](../../tests/README.md).
