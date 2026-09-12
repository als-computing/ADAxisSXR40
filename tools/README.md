# tools/

Small standalone programs written alongside the driver — one folder per tool, each with
its own README, build line and the document that motivated it. Nothing here is built by
the EPICS `make`; build each by hand as its README says.

| Tool | What it does | Came from |
|---|---|---|
| [h5check/](h5check/) | Reads an areaDetector HDF5 file back with an independent HDF5 build and reports shape, per-frame pixel statistics, `NDArrayUniqueId` continuity and the frame rate from the in-file camera timestamps. The check that found the camera emitting a test pattern instead of images. | [info/performance/README.md](../info/performance/README.md), "Verifying the files are real" |

## h5check and the test suite

`tests/run.sh full` builds `h5check` into `tests/.build/h5check` (gcc against ADSupport's
HDF5, `-lhdf5 -lhdf5_hl -lszip -lzlib`) and `tests/files/test_hdf5_stream.py` uses it to
verify every file the IOC writes: dimensions, dtype, contiguous unique ids, camera fps
from the stored timestamps, and whether the frames are the synthetic ramp.

### h5check options and exit codes (2026-09-11)

```
h5check [-l] file.h5
```

- The dims line now ends with ` filters=[<ids>]`, followed by one `  filter <id>: available|UNAVAILABLE`
  line per filter in the dataset's pipeline (all areaDetector filters are compiled into ADSupport's
  HDF5, so UNAVAILABLE means a reader built against another HDF5).
- `-l` adds `  NDAttributes: <names>` (children of `/entry/instrument/NDAttributes`) and
  `  datasets: <paths>` (which of the standard paths exist): the file contract
  `tests/workflow/test_hdf5_contract.py` asserts.
- Exit 0 ok; 1 cannot open the file or `/entry/data/data`; 2 a sampled frame could not be read.
  Every pre-existing output line keeps its format.
