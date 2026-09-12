# files/ — full tier; needs the camera and real storage

HDF5 stream of 10 full frames verified with `tools/h5check` (built into `tests/.build/`
against ADSupport's HDF5, not the IOC's), and one TIFF. Output goes to `--outdir`
(default `~/axis-perf-tmp`), never tmpfs, and is deleted afterwards.
