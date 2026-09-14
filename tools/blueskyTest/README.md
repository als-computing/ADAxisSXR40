# tools/blueskyTest — the detector under bluesky, before it goes into a queue-server

Two files, meant to be lifted into a queue-server startup directory later:

| File | What |
|---|---|
| [`area_detectors.py`](area_detectors.py) | The ophyd device for the XV4040 detector, in six marked sections: **1. CONFIGURATION** (every value to set in advance: data root and dated directory, prefix and name, the camera / writer / Stats1 settings applied at `stage()`, what `read()` returns, the HDF5 dataset path and resource spec, the dtype map), 2. `TucsenCam` (records both drivers have), 3. `XV4040HDF5Plugin` (HDF5 writer as a bluesky file store, tiled-readable resource, our own `warmup()`), 4. `XV4040Detector` (`SingleTrigger` + `DetectorBase`), 5. `make_detector()` (connects, applies section 1), 6. `xv4040 = make_detector()` at import, the way bluesky-web's [`02_area_detectors.py`](https://github.com/als-computing/bluesky-web/blob/main/queue-server/startup_bl531/02_area_detectors.py) instantiates its Basler and Pilatus devices. To adapt it to another root, prefix or exposure, edit section 1 only. |
| [`main.py`](main.py) | The test: a `RunEngine`, ophyd's virtual `motor`, `scan([xv4040], motor, -1, 1, N)` with a `LiveTable` and bluesky's **`TiledWriter`** writing into a temporary `tiled serve catalog`; then the run's documents, the HDF5 file and the image stack as tiled serves it are checked. |
| [`qserver_test.py`](qserver_test.py) | The same scan through a **real queue-server**: embedded Redis, temporary tiled, `start-re-manager` with this file in its startup directory, items queued over ZMQ, history and tiled checked. `run.sh qserver`. |
| [`run.sh`](run.sh) | Creates `.venv` (bluesky, ophyd, h5py, `tiled[all]`, and for `qserver` also bluesky-queueserver + redislite, over the system pyepics) on first use and runs `main.py` or `qserver_test.py`; pins Channel Access to this host like `tests/run.sh`. |

```bash
tools/blueskyTest/run.sh                    # 5 points; file checked directly and through tiled, then deleted
tools/blueskyTest/run.sh --points 10 --keep # keep the file under ~/axis-perf-tmp/bluesky/<date>/
tools/blueskyTest/run.sh --no-tiled         # documents + file only
XV4040_DATA_ROOT=/data/xv4040 tools/blueskyTest/run.sh   # another root (must be writable by the IOC's user)
```

## What `main.py` checks

1. The device connects and the detector is `Idle`; a warm-up frame teaches the HDF5 plugin
   the current geometry (Stream mode fixes the dataset shape when Capture starts).
2. The scan completes with `exit_status success`, one event per point, each carrying the
   `xv4040_image` datum key; the descriptor gives that key `shape [1, rows, cols]`,
   `dtype_numpy` and `dtype_str` `<u2`, `external FILESTORE:`; datum `point_number`s are
   `0..N-1`; exactly one resource document, spec `AD_HDF5_SWMR_STREAM`, with `dataset`,
   `swmr` and `chunk_shape` parameters.
3. The file named by the resource (`root` + `resource_path`) exists, and inside it
   `/entry/data/data` has shape `(N, rows, cols)` and dtype `uint16`, the `NDArrayUniqueId`
   attribute is contiguous, no frame is constant, and the frames are not the camera's
   synthetic ramp (mean 32640).
4. **Tiled**: a `tiled serve catalog --temp` is started on a free local port with our data root
   as readable storage, `TiledWriter(client)` is subscribed to the RunEngine, and after the run
   `client[uid]["primary"]["xv4040_image"]` has shape `(N, rows, cols)`, dtype `uint16`, and its
   frame 0 equals the file's frame 0 pixel for pixel (mean compared). The scalars
   (`motor`, `xv4040_stats1_mean_value`, ...) are there beside it.

Exit 0 when all hold, 1 with a `FAIL:` line otherwise. The file is deleted unless `--keep`;
the temporary tiled server is stopped either way.

## Why the resource spec is `AD_HDF5_SWMR_STREAM`

ophyd's `FileStoreHDF5` stamps its resources `AD_HDF5`. bluesky's `TiledWriter` maps specs to
MIME types through a fixed table; `AD_HDF5` is **not** in it, so such a run is stored with an
`application/octet-stream` asset that tiled cannot open. `AD_HDF5_SWMR_STREAM` is in the table
(`application/x-hdf5`) and describes the same layout, frames stacked in `/entry/data/data`.
The plugin therefore sets that spec and adds the parameters tiled's HDF5 consolidator reads:
`dataset="/entry/data/data"`, `swmr=False` (NDFileHDF5 does not write in SWMR mode) and
`chunk_shape=(1, rows, cols)`. Result on 2026-09-14: tiled served the 5-frame stack with the
right shape, dtype and pixels. Without the spec change the writer accepted the run but the image
could not be read back.

## Choices that differ from the reference file

- **HDF5, not TIFF.** `FileStoreHDF5IterativeWrite` + `HDF5Plugin_V34` (ADCore R3-14): one
  file per scan in Stream mode with `num_capture 0`, closed at unstage. `num_capture` is
  placed in front of the mixin's `stage_sigs` because it must be written before `capture=1`.
- **Own `warmup()`.** ophyd's writes `TriggerMode="Internal"`, which this camera's enum does
  not have (`Free Run`, `Standard`, `Synchronous`, `Global`, `Software`). Ours acquires one
  Single frame with callbacks on, with the writer's `AutoSave` off for the duration (a
  Single-mode writer would otherwise save the warm-up frame as a stray `_001.h5`), waits on the
  camera's counter (the file plugin counts only arrays it saves), and restores what it touched
  even on failure.
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

## Line-by-line against the reference (checked 2026-09-14)

| Reference file (`02_area_detectors.py`) | Here |
|---|---|
| `FILES_ROOT` / `IMAGE_DIR` constants, `%Y/%m/%d` in the path | same (`XV4040_FILES_ROOT`, `XV4040_IMAGE_DIR`), root also overridable by `XV4040_DATA_ROOT` |
| `CamBase` subclass with common + camera-specific `EpicsSignal`s | `TucsenCam`: temperature, bin mode, frame format, fan gear; the common ones come from `CamBase` |
| `FileStoreTIFFIterativeWrite` + `TIFFPlugin` | `FileStoreHDF5IterativeWrite` + `HDF5Plugin_V34` (HDF5 is what this IOC writes) |
| `describe()` override: shape `[num_images, height, width]` for Mono, `dtype_str` from `DataType` | same override on the HDF5 plugin; ophyd 1.11 also emits `dtype_numpy` on its own |
| `SingleTrigger, DetectorBase` with `cam`, `image`, file plugin as `ADComponent`s | same, plus `stats1` for two per-point scalars |
| `stage_sigs`: `image_mode Single`, `num_images 1`, `acquire_time`, `acquire_period`, `file_template` | camera: `trigger_mode Free Run` (a hardware trigger mode left behind would hang the scan), `num_images 1`, `acquire_time`, `array_callbacks 1`; `image_mode` is `Multiple` from `SingleTrigger` (one frame either way); `acquire_period` not set, this driver derives the period from exposure and readout. Writer: `nd_array_port TUCSEN`, `num_extra_dims 0`, `xml_file_name ""`, `swmr_mode 0` (so the dataset is the plain `/entry/data/data` stack the resource promises), `num_capture 0` ahead of `capture 1`, `auto_increment`, `compression None`; `file_template` is ophyd's `%s%s_%6.6d.h5`. ophyd's bases add `enable`, `blocking_callbacks Yes`, `create_directory -3`, `array_counter 0`, `auto_save`. Stats1: `nd_array_port TUCSEN`, `compute_statistics`. Not staged on purpose: the ROI and binning (the operator's choice). |
| `read_attrs = ['tiff']`, `tiff.read_attrs = []` (for the tiled writer) | `read_attrs = ["hdf5", "stats1"]`, `hdf5.read_attrs = []`; **verified with the TiledWriter itself**, not only the descriptor keys (section above) |
| device instantiated at import inside `try/except` with a message | same (`xv4040 = make_detector()`), with `wait_for_connection` so a missing IOC fails there |
| Pilatus devices, `root_str`/`md` constructor extras, RGB/Bayer shape branch | not carried: one detector, one color mode |

## Queue-server, end to end (2026-09-14)

[`qserver_test.py`](qserver_test.py) (`run.sh qserver`) runs the real thing, all on this host and
torn down afterwards: an embedded Redis (`redislite`, no root, no system service), a temporary
tiled server, and `start-re-manager --startup-dir` on a directory holding `00_base.py`
(RunEngine with the TiledWriter subscribed, `motor`, `scan`, `count`), the stock
`user_group_permissions.yaml`, and this `area_detectors.py` as `02_area_detectors.py`. Over the
manager's ZMQ API it opens the environment, queues `warmup_xv4040` and
`scan([xv4040], motor, -1, 1, 3)`, starts the queue, and reads the history and the run:

```
devices allowed: ['motor', 'xv4040']
plans allowed:   ['count', 'scan', 'warmup_xv4040']
queue finished in 4.0 s
history: warmup_xv4040    exit_status=completed
history: scan             exit_status=completed run_uids=['c52b0e7c-...']
tiled: c52b0e7c/primary/xv4040_image shape=(3, 4096, 4096) dtype=uint16
asset uri: file://localhost/home/gabrielgazolla/axis-perf-tmp/bluesky/2026/09/14/d90fe0c3-..._000000.h5
file d90fe0c3-..._000000.h5: shape=(3, 4096, 4096); frame0 mean file=1619.1 tiled=1619.1
OK: queue-server ran warmup_xv4040 and scan([xv4040], motor, -1, 1, 3); tiled serves 3 frames of 4096x4096 uint16
```

So the file works as a queue-server startup file as it stands (bluesky-queueserver 0.0.25):
the worker loads it, registers the device and the plan, executes a queued scan against the
IOC, and the TiledWriter in the worker produces a run whose image stack tiled serves.
Things to know when deploying:

- **Run `warmup_xv4040` once** after the worker environment opens and after every ROI or
  binning change, before the first scan. Otherwise the first Stream capture at a new geometry
  writes an empty file with "Invalid frame" in the IOC log.
- **Environment**: `XV4040_DATA_ROOT` (data root writable by the IOC's user) and
  `XV4040_PREFIX` can be set in the worker's environment instead of editing section 1.
  Channel Access needs `EPICS_CA_ADDR_LIST=127.0.0.1 EPICS_CA_AUTO_ADDR_LIST=NO` on this host,
  as `run.sh` sets, because both IOCs answer to the same prefix.
- **The IOC must be up when the worker opens** its environment: `make_detector()` waits up to
  10 s for the connection and otherwise leaves `xv4040 = None` with a printed message, as the
  reference file does; plans then fail with a clear error instead of hanging.
- **TiledWriter**: subscribe it in the worker (`RE.subscribe(TiledWriter(client))`); the
  resource spec and parameters this device emits are what it needs (section above).

To repeat: `tools/blueskyTest/run.sh qserver` (add `--keep` to keep the temp startup directory,
the manager log and the HDF5 file for inspection).

## Not covered here

Hardware triggering (`TriggerMode` other than `Free Run`), and the beamline's own
queue-server deployment (its Redis, its tiled, its permissions file): what was run here is
the same software on this host with temporary instances of each.
