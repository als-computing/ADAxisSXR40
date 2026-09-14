# tools/blueskyTest — the detector under bluesky, before it goes into a queue-server

Two files, meant to be lifted into a queue-server startup directory later:

| File | What |
|---|---|
| [`area_detectors.py`](area_detectors.py) | The ophyd device for the XV4040 detector, in six marked sections: **1. CONFIGURATION** (every value to set in advance: data root and dated directory, prefix and name, the camera / writer / Stats1 settings applied at `stage()`, what `read()` returns, the HDF5 dataset path and resource spec, the dtype map), 2. `TucsenCam` (records both drivers have), 3. `XV4040HDF5Plugin` (HDF5 writer as a bluesky file store, tiled-readable resource, our own `warmup()`), 4. `XV4040Detector` (`SingleTrigger` + `DetectorBase`), 5. `make_detector()` (connects, applies section 1), 6. `xv4040 = make_detector()` at import, the way bluesky-web's [`02_area_detectors.py`](https://github.com/als-computing/bluesky-web/blob/main/queue-server/startup_bl531/02_area_detectors.py) instantiates its Basler and Pilatus devices. To adapt it to another root, prefix or exposure, edit section 1 only. |
| [`main.py`](main.py) | The test: a `RunEngine`, ophyd's virtual `motor`, `scan([xv4040], motor, -1, 1, N)` with a `LiveTable` and bluesky's **`TiledWriter`** writing into a temporary `tiled serve catalog`; then the run's documents, the HDF5 file and the image stack as tiled serves it are checked. |
| [`run.sh`](run.sh) | Creates `.venv` (bluesky, ophyd, h5py, `tiled[all]` over the system pyepics) on first use and runs `main.py`; pins Channel Access to this host like `tests/run.sh`. |

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
| `stage_sigs`: `image_mode Single`, `num_images 1`, `acquire_time`, `acquire_period`, `file_template` | `num_images 1`, `acquire_time`; `image_mode` is `Multiple` from `SingleTrigger` (one frame either way); `acquire_period` not set, this driver derives the period from exposure and readout; `file_template` is ophyd's `%s%s_%6.6d.h5`; plus `num_capture 0` ahead of `capture 1` |
| `read_attrs = ['tiff']`, `tiff.read_attrs = []` (for the tiled writer) | `read_attrs = ["hdf5", "stats1"]`, `hdf5.read_attrs = []`; **verified with the TiledWriter itself**, not only the descriptor keys (section above) |
| device instantiated at import inside `try/except` with a message | same (`xv4040 = make_detector()`), with `wait_for_connection` so a missing IOC fails there |
| Pilatus devices, `root_str`/`md` constructor extras, RGB/Bayer shape branch | not carried: one detector, one color mode |

## Not covered here

Hardware triggering (`TriggerMode` other than `Free Run`), the tiled writer, and the
queue-server itself. The device is written so that dropping `area_detectors.py` into the
startup directory and calling `scan([xv4040], motor, ...)` from a queue item is the next step.
