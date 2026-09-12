# Functional tests for the ADAxisSXR40 IOC

pytest suite run against the **live IOC and camera**. It exercises every PV the IOC
serves, verifies the fixes that justify this fork of ADTucsen, checks boot health from
the console log, and compares our IOC with a recorded snapshot of Damon English's
`ioc-xv4040` (ADTucsen). The suite **never starts or stops a service** and **restores
every setting it changes**.

```bash
tests/run.sh              # smoke tier (default): ~3.5 min, no disk writes, no sustained load
tests/run.sh full         # + file writes, robustness, workflow, performance regression, compat (~8 min)
tests/run.sh stress       # sustained-load tier by group: matrix roi compression (~7 min, ~30 GB written)
tests/run.sh stress all   # + long cycles load (~16 min); see stress/README.md for every option
tests/run.sh static       # tests that need no IOC at all (what CI runs)
tests/run.sh selftest     # static + boot + PV inventory: is the harness wired?
tests/run.sh capture      # dump every PV of the serving IOC to compat/baselines/<driver>-<date>.json
tests/run.sh smoke -- -k roi -v        # anything after -- goes to pytest
```

First run creates `tests/.venv` (`python3 -m venv --system-site-packages` + `pip install
pytest`) so pytest sits on top of the system pyepics and numpy; the stress tier also adds
`p4p` (pvAccess client for the viewer test; optional, that test skips without it). Results
and reports go to `tests/.results/` (gitignored).

## Which driver is serving?

The suite detects it: `systemctl is-active` on `ioc-axissxr40` and `ioc-xv4040`, then a
running `st.cmd` process, then the capability-audit line in our log. It then loads that
driver's expectations (`helpers/expected.py` or `helpers/expected_adtucsen.py`), so the
**same suite runs against Damon's IOC**:

| Marker | On ADAxisSXR40 | On ADTucsen |
|---|---|---|
| (none) | must pass | must pass |
| `ours_only` | must pass | skipped |
| `fork_fix` | must pass | **xfail**, reason names the ADTucsen defect; an XPASS means his driver fixed it |
| `hardware_state` | documents the camera's current state | same |
| `full` | only with `--full` | same |
| `stress` | only via `tests/run.sh stress` | same (his log if readable) |

Swapping drivers is the manual two-command procedure in
[../info/systemd/README.md](../info/systemd/README.md). A/B session: run `smoke` on ours,
swap, run `smoke` and `capture` on his, swap back, run `full` (the compat comparison).

## Folders

| Folder | Needs | What it checks |
|---|---|---|
| `static/` | nothing | template drvInfo ↔ driver `createParam` (the rename bug), request files, `st.cmd` and systemd files, documentation links, template diff vs ADTucsen, the helpers themselves |
| `boot/` | IOC | last-boot log slice: capability audit, `N of N PV's connected`, exactly the 8 expected write errors, no warnings; autosave file complete and covering every plugin; one PVA server; the guard refuses a second IOC |
| `pvs/` | IOC | every template record connects with the right type and enum strings; identity strings; safe setpoints round-trip |
| `driver/` | camera | ROI alignment (SizeY/MinY to 4 is ours; width 8 and MinX 4 the camera does itself), height clamp, AutoLevels→Histogram, FrameFormat bounds, exposure quantisation, ReverseY readback tolerance |
| `acquire/` | camera | Single/Multiple/Continuous, software trigger, exposure applied, plugins delivering, PVA image, cross-transport equality, pool cap, timestamps, the writers' error paths |
| `image/` | camera | pixel sanity: not the synthetic ramp (hard assertion since 2026-09-11), frames differ, dark mean (expected failure until checked at the detector) |
| `files/` | camera, disk | HDF5 stream + `h5check` (incl. frame-interval jitter), TIFF single |
| `robustness/` | camera | 20 start/stop cycles at 32 rows with the deadlock probe, binning, long exposure, writes during acquisition, pool leak |
| `workflow/` | camera, disk | the ophyd scan sequence (one file per scan and per point) and the HDF5 file contract (dataset paths, NDAttributes set) |
| `performance/` | camera | `roi-rate-test.sh` (moved here from `info/performance/`) and a 5 % regression check against the recorded rates |
| `compat/` | IOC, baseline | every PV of ours vs the recorded ADTucsen baseline; only the intended differences allowed |
| `stress/` | camera, disk | **own tier**: HDF5 streaming 10–100 s at several heights, long continuous run, 30 capture cycles, a PVA viewer watching, every compression, ROI switching, and the provoked writer-queue test; measurements recorded ([stress/README.md](stress/README.md)) |
| `manual/` | hardware | procedures that cannot be automated: trigger in/out, TEC, autosave round-trip |

## Safety

- `helpers/policy.py` is the only place that says what may be written. `CA.put()` refuses
  anything else. TEC, temperature setpoint, fan, shutter, trigger-out and the 8
  unsupported controls are never written.
- A session snapshot is taken at start and restored at the end (offsets before sizes,
  AutoLevels before Histogram). Any mismatch is written to `tests/.results/restore-failures.txt`.
- The deadlock probe from `roi-rate-test.sh` runs after every stop. If it fires, the
  session stops issuing hardware writes and points at `info/incidents/stop-deadlock.md`.
- File-writer tests refuse `tmpfs` output and delete what they wrote; the stress tier also
  checks free space before every run and caps the bytes written per session.
- The IOC log is watched during the whole session (`helpers/logdelta.py`): new error lines
  outside a test's declared error window are listed in `tests/.results/log-delta.txt` and
  raised as a warning; in the stress tier they fail the responsible run.

## Future work (not implemented)

- **Lifecycle tier** (needs a sudoers rule for `systemctl start/stop/restart ioc-axissxr40`
  only): clean stop within `TimeoutStopSec`, procServ restarting a killed child, an autosave
  round-trip across a restart with `boot/` green afterwards.
- **Build test**: `make` from clean, zero warnings, `static/` green on the result.
- **Camera health baselines** once the sensor is confirmed dark at the detector: dark mean and
  sigma vs exposure, hot-pixel count, against the characterisation notes.
- **Trigger hardware**: the `manual/` procedures with a pulse generator.

## Expected results today (2026-09-11)

`smoke`: all pass; two expected failures remain: the camera record's own timestamp PVs
are not published by the driver (`acquire/test_timestamps.py`, a known gap in both
drivers) and the dark-frame mean is ~1650 ADU instead of tens (`image/`, hardware state to
be confirmed at the detector). The synthetic-ramp check is a hard assertion since the ramp
cleared on 2026-09-11. `full` additionally needs the ADTucsen baseline for `compat/`;
without one those tests skip with the capture command. When a number changes legitimately
(a plugin added, a fix upstream), edit `helpers/expected.py` and say why in the commit.

## What the suite found while being written (2026-09-11)

- `commonPlugin_settings.req` stale copy in `iocBoot/` silently dropping 104 autosave PVs
  (fixed; `static/test_req_files.py` and `boot/test_autosave_file.py` guard it).
- `cam1:TimeStamp_RBV`, `EpicsTSSec_RBV`, `UniqueId_RBV` never published by the driver.
- `ReverseY` does round-trip on our driver; the 'does not take' of July/August was ADTucsen
  discarding the SDK's NO_RESOURCE reply (see below).
- The camera's synthetic ramp cleared during the first full run, probably on the binning cycle.
- Running the suite on Damon's IOC (234 passed): the camera itself rounds width and MinX, so
  those are not fork differences; the upstream height-clamp bug is masked by the GetROI
  readback; `ReverseY` 'not taking' was ADTucsen discarding a NO_RESOURCE write, not the
  camera refusing it. The real fork-fix set: AutoLevels→Histogram, RGB888 rejection,
  ReverseY readback tolerance, SizeY/MinY alignment.
- A CA put with completion callback on a busy record (`HDF1:Capture`, `cam1:Acquire`)
  blocks until the record returns to 0, so `Capture 1` with `NumCapture 0` never completes:
  the IOC logs `put call back time out` and the client's channels go dead. `helpers/ca.py`
  writes the records in `policy.NO_CALLBACK` without a callback.
- `Pva1:Image` monitors with a sub-field request (`field(uniqueId)`) never update; only the
  full request does (QSRV records update either way). ADCore behaviour, same on both IOCs.
- Starting a continuous acquisition costs ~256 MB of RSS once (8 full frames of SDK
  transfer buffers), released at stop; steady-state RSS is flat.
