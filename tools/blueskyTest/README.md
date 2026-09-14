# tools/blueskyTest — the detector under bluesky, before it goes into a queue-server

Two files, meant to be lifted into a queue-server startup directory later:

| File | What |
|---|---|
| [`area_detectors.py`](area_detectors.py) | The ophyd device for the XV4040 detector: `TucsenCam` (records both drivers have), `XV4040HDF5Plugin` (HDF5 writer as a bluesky file store, one file per scan, our own `warmup()`), `XV4040Detector` (`SingleTrigger` + `DetectorBase`), and `xv4040 = make_detector()` at import, the way bluesky-web's [`02_area_detectors.py`](https://github.com/als-computing/bluesky-web/blob/main/queue-server/startup_bl531/02_area_detectors.py) instantiates its Basler and Pilatus devices. |
| [`main.py`](main.py) | The test: a `RunEngine`, ophyd's virtual `motor`, `scan([xv4040], motor, -1, 1, N)`, then the run's documents and HDF5 file are checked. |
| [`run.sh`](run.sh) | Creates `.venv` (bluesky, ophyd, h5py over the system pyepics) on first use and runs `main.py`; pins Channel Access to this host like `tests/run.sh`. |

```bash
tools/blueskyTest/run.sh                    # 5 points; file checked, then deleted
tools/blueskyTest/run.sh --points 10 --keep # keep the file under ~/axis-perf-tmp/bluesky/<date>/
XV4040_DATA_ROOT=/data/xv4040 tools/blueskyTest/run.sh   # another root (must be writable by the IOC's user)
```

## What `main.py` checks

1. The device connects and the detector is `Idle`; a warm-up frame teaches the HDF5 plugin
   the current geometry (Stream mode fixes the dataset shape when Capture starts).
2. The scan completes with `exit_status success`, one event per point, each carrying the
   `xv4040_image` datum key; datum `point_number`s are `0..N-1`; exactly one `AD_HDF5`
   resource document.
3. The file named by the resource (`root` + `resource_path`) exists, and inside it
   `/entry/data/data` has shape `(N, rows, cols)` and dtype `uint16`, the `NDArrayUniqueId`
   attribute is contiguous, no frame is constant, and the frames are not the camera's
   synthetic ramp (mean 32640).

Exit 0 when all hold, 1 with a `FAIL:` line otherwise. The file is deleted unless `--keep`.

## Choices that differ from the reference file

- **HDF5, not TIFF.** `FileStoreHDF5IterativeWrite` + `HDF5Plugin_V34` (ADCore R3-14): one
  file per scan in Stream mode with `num_capture 0`, closed at unstage. `num_capture` is
  placed in front of the mixin's `stage_sigs` because it must be written before `capture=1`.
- **Own `warmup()`.** ophyd's writes `TriggerMode="Internal"`, which this camera's enum does
  not have (`Free Run`, `Standard`, `Synchronous`, `Global`, `Software`). Ours acquires one
  Single frame with callbacks on and restores what it touched.
- **`read_attrs = ["hdf5"]`, `hdf5.read_attrs = []`**, as in the reference: the event carries
  the datum, never the 32 MiB image over Channel Access. `image` and `stats1` are declared
  (a viewer or a plan may use them) but omitted from reads.
- **Works on both drivers.** Only records present in both templates are declared; the file
  checks are geometry-relative. Verified 2026-09-14 against ADTucsen (`ioc-xv4040`, the IOC
  serving that day: 5 points, 168.8 MB, shape (5, 4096, 4096), 3.4 s); the same run against
  ADAxisSXR40 is due at the next swap.
- **Directory permissions.** The IOC creates the file as its own user; `main.py` creates the
  dated directory with mode 0777 so `ioc-xv4040` (user `daenglis`) can write into our
  `axis-perf-tmp` root. In production the root will be the beamline data mount.

## Not covered here

Hardware triggering (`TriggerMode` other than `Free Run`), the tiled writer, and the
queue-server itself. The device is written so that dropping `area_detectors.py` into the
startup directory and calling `scan([xv4040], motor, ...)` from a queue item is the next step.
