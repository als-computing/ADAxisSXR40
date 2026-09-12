# Test report: ADAxisSXR40 and ADTucsen on the XV4040 detector — 2026-09-11

**Summary.** One test suite, 12 categories, 327 tests, run against both EPICS drivers for the
Dhyana XV4040 detector on `bl1101ad01`: our ADAxisSXR40 and Damon English's ADTucsen
(`ioc-xv4040`). **Every test passes on both drivers.** The only non-passes are 3 expected
failures shared by both (items of the camera or of areaDetector itself) and, on ADTucsen, the
6 tests that check the fixes this fork exists for, which fail there by design. Both IOCs serve
the same PV names (`XV4040:`), swap with two `systemctl` commands, and both held sustained
streaming to disk for minutes with every HDF5 file verified inside.

## Results by category

| Category | What it proves | Tests | ADAxisSXR40 | ADTucsen |
|---|---|---|---|---|
| static | template ↔ driver parameters, autosave request files, startup and systemd files, documentation links (no IOC needed; runs in CI) | 93 | 93 pass | 93 pass |
| boot | console log of the last boot: all PVs connected, exactly the expected write errors, no warnings; autosave file complete; one PVA server; start guard | 22 | 22 pass | 20 pass, 2 n/a¹ |
| pvs | every record connects with the right type and enum strings; identity strings; every safe setpoint round-trips | 61 | 61 pass | 59 pass, 2 n/a¹ |
| driver | ROI alignment, height clamp, AutoLevels→Histogram, frame-format bounds, exposure quantisation, ReverseY | 32 | 32 pass | 25 pass, 6 expected fail², 1 n/a¹ |
| acquire | Single / Multiple / Continuous, software trigger, exposure applied, all plugins delivering, PVA image, CA vs PVA equality, pool cap, timestamps, writer error paths | 64 | 63 pass, 1 xfail³ | 61 pass, 1 xfail³, 2 n/a¹ |
| image | real sensor data (not a test pattern), frames differ, dark level | 4 | 3 pass, 1 xfail⁴ | 3 pass, 1 xfail⁴ |
| files | HDF5 stream verified in-file (dims, dtype, chunking, unique ids, frame intervals), TIFF single | 7 | 6 pass, 1 xfail⁴ | 6 pass, 1 xfail⁴ |
| robustness | 20 start/stop cycles at 32 rows with the deadlock probe, binning, 5 s exposure, writes during acquisition, pool leak | 7 | 7 pass | 7 pass |
| workflow | the ophyd scan sequence (one file per scan, one file per point) and the HDF5 file contract (dataset paths, NDAttributes) | 5 | 5 pass | 5 pass |
| performance | frame rate at every ROI height within 5 % of the recorded reference | 3 | 3 pass | 3 pass |
| compat | every one of our 7533 PVs against the 7529 recorded from ADTucsen: only the 7 intended differences | 12 | 12 pass | is the baseline |
| stress | sustained load, own tier (below) | 17 | 17 pass | 17 pass |
| **Total** | | **327** | **324 pass, 3 xfail** | **299 pass, 9 xfail, 19 n/a** |

¹ "n/a": tests of things that exist only in ADAxisSXR40 (its systemd guard, its 4 extra records, its capability audit) or of the environment (his IOC runs as another user).
² The fork's fixes, absent upstream by definition: SizeY/MinY alignment to 4 (3 tests), AutoLevels publishing Histogram, RGB888 rejected on a mono sensor, ReverseY readback. Each is marked as expected to fail on ADTucsen with the reason; if his driver gained the fix the test would flag it.
³ Neither driver publishes the camera record's own timestamp/unique-id PVs (the plugins carry them). Known gap, same in both.
⁴ Hardware state, not software: the dark-frame mean reads ~1650 ADU where ~68 is expected; to be checked at the detector.

Run times: ADAxisSXR40 static 18:52, smoke tier 18:18, writer error paths and workflow 17:33, files / robustness / performance / compat and the one full-tier driver test 16:23, stress 18:07 to 18:17 and provoke 17:59. ADTucsen: stress 18:40 to 18:51, provoke 18:51, full tier 18:51 to 18:58. All on 2026-09-11.

## Stress tier: both drivers under sustained load

Uncompressed HDF5 streaming with the full plugin chain on, every file checked with
`tools/h5check` (dimensions, data type, chunking, contiguous unique ids, frame intervals,
per-frame statistics) and deleted afterwards. 46 streaming runs and about 60 GB written per driver.

| Run | ADAxisSXR40 | ADTucsen |
|---|---|---|
| Full frame 4096 rows, 25 s | 210 frames, camera 8.6 fps, writer 8.38 fps, 281 MB/s, 0 drops, max frame gap 120 ms (nominal 116) | identical: 8.38 fps, 281 MB/s, 0 drops, max gap 125 ms |
| 256 rows, 25 s | 3148 frames, camera 137 fps, writer 134 fps, 280 MB/s, 0 drops | identical |
| 32 rows, 5 s | 4726 frames, 1038 fps camera, 943 fps writer, 0 drops | identical |
| ROI switching 4096 → 32 → 1024 → 4096 | clean at every step, deadlock probe passed after each stop | identical |
| 5 compressions (none, zlib, Blosc, Bitshuffle-LZ4, LZ4) | all complete and readable; Blosc/Bitshuffle 1.5×, zlib 1.34×, LZ4 1.0× | identical |
| 5 min continuous, plugins off | 8.63 to 8.67 fps at every 30 s sample, memory flat, telemetry updating | identical (8.63 to 8.67 fps, memory flat) |
| 30 capture cycles at 1024 rows, 12.6 GB | 30 identical 419.5 MB files, FileNumber correct, memory flat | identical |
| 25 s full frame with a pvAccess viewer subscribed and statistics computing | 0 drops; the viewer received every frame (7.1 GB) | identical |
| Provoked overflow (writer queue 1, zlib 6, continuous) | 77 frames dropped *at the plugin* and counted, 6 written, pool peak 390 MB of 1907, IOC back to Idle | identical behaviour, pool peak 318 MB |

Neither driver dropped a frame or grew in memory during normal operation; both degrade
the intended way when a writer is deliberately starved. Full tables:
[ADAxisSXR40](../performance/2026-09-11-stress-adaxissxr40-bl1101ad01.md),
[ADTucsen](../performance/2026-09-11-stress-adtucsen-bl1101ad01.md).

## Interchangeability

- Same prefix `XV4040:`, same asyn port, same plugin chain, same autosave layout. A client
  cannot tell them apart except by the 7 intended differences: 4 records that only
  ADAxisSXR40 has (TEC enable, ring-buffer counters), RGB888 removed from the frame-format
  menu (the sensor is mono and RGB888 stalls it), and the sensor temperature published with
  the per-unit calibration and two decimals (ADTucsen publishes the raw SDK value: the same
  sensor read 10.3 °C on ours and −2.7 on his during these runs).
- Swap is `systemctl stop` one, `systemctl start` the other. ADTucsen remains the default at
  boot; the ADAxisSXR40 unit is installed but not enabled, and its start guard refuses to run
  while `ioc-xv4040` is active.
- The suite detects which IOC is serving and loads that driver's expectations, which is how the
  same tests produced both columns above.

## What the suite is

`ADAxisSXR40/tests/`, pytest, `tests/run.sh smoke|full|static|stress`. The suite never starts
or stops a service, restores every setting it changes, refuses to write any PV outside an
allow-list, runs the deadlock probe after every acquisition stop, watches the IOC log for new
errors during the whole session, and deletes every file it writes after verifying it. The
static tier runs in CI on every push. Method and per-folder detail:
[tests/README.md](../../tests/README.md).
