# tools/

Small standalone programs written alongside the driver — one folder per tool, each with
its own README, build line and the document that motivated it. Nothing here is built by
the EPICS `make`; build each by hand as its README says.

| Tool | What it does | Came from |
|---|---|---|
| [h5check/](h5check/) | Reads an areaDetector HDF5 file back with an independent HDF5 build and reports shape, per-frame pixel statistics, `NDArrayUniqueId` continuity and the frame rate from the in-file camera timestamps. The check that found the camera emitting a test pattern instead of images. | [info/performance/README.md](../info/performance/README.md), "Verifying the files are real" |
