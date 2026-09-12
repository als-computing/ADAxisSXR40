# stress/ — sustained load; its own tier, `tests/run.sh stress`

Not part of `smoke` or `full`. Minutes long and tens of GB written, so it is selected by
group and never by accident:

```bash
tests/run.sh stress                          # matrix roi compression  (~7 min, ~30 GB written)
tests/run.sh stress all                      # + long cycles load       (~16 min)
tests/run.sh stress matrix --stress-durations 10,25,50,100 --stress-heights 4096,1024,256,32   # full matrix, ~18 min
tests/run.sh stress matrix --stress-heights all      # the nine sweep heights (deliberate; ~45 min)
tests/run.sh stress long --long-minutes 30
tests/run.sh stress provoke                  # the deliberately provoked writer-queue test
tests/run.sh stress all --record             # also write info/performance/<date>-stress-<driver>-<host>.md
```

| Group | File | What | Default cost |
|---|---|---|---|
| `matrix` | `test_stream_matrix.py` | HDF5 stream for each duration × height; complete, no drops anywhere, uid contiguous, writer within 15 % of the recorded rate, pool < 90 % of cap, RSS growth < 50 MB, no new log errors, frame-interval bound | 10 s and 25 s × 4096 and 256 rows: ~2.5 min, 19 GB |
| `roi` | `test_roi_switching.py` | 5 s captures at 4096 → 32 → 1024 → 4096 rows | ~1.5 min, 5 GB |
| `compression` | `test_compression_variants.py` | None, zlib, Blosc, BSLZ4, LZ4 at 256 rows, camera held at 50 fps (10 fps for zlib, whose single thread manages ~27 fps here); correctness, ratio recorded | ~2 min, 5 GB |
| `long` | `test_long_continuous.py` | continuous, plugins off, sampled every 30 s: rate, RSS, telemetry updating | 5 min, 0 GB |
| `cycles` | `test_capture_cycles.py` | 30 × 50 frames at 1024 rows to new files; FileNumber, RSS drift | ~3 min, 12.6 GB |
| `load` | `test_realistic_load.py` | 25 s full frame to HDF5 with a pvAccess viewer (`helpers/pva_viewer.py` on p4p) receiving every frame and Stats computing | ~1 min, 7 GB |
| `provoke` | `test_provoke_queue.py` | writer queue 1 + zlib 6: frames must drop at the plugin, IOC stays alive, pool under cap | ~0.5 min |

**Disk.** Every run writes one file, checks it with `tools/h5check` (built into
`tests/.build/`) and deletes it before the next run, so the peak on disk is one file plus a
1.5× margin (7 GB for the default matrix, 28 GB for a 100 s full-frame run). Free space is
checked before each run and a session cap (`--max-bytes`, default 80 GB) skips runs rather
than filling the disk. Output goes to `--outdir` (default `~/axis-perf-tmp`, never tmpfs).

**Why Multiple mode.** `NumImages` equals `NumCapture`, so the camera stops itself when the
file is complete. In continuous mode the frames still streaming while the file closes are
counted as drops although every requested frame is in the file.

**The viewer.** `tests/run.sh stress` installs `p4p` into `tests/.venv` the first time (the
`load` group skips if that fails). `helpers/pva_viewer.py` subscribes to `Pva1:Image` with
the full request, as c2dataviewer and ImageJ do, and prints one line per frame; measured
2026-09-11: 32 MiB frames at the camera's 8.6 fps, none missed. `pvmonitor` cannot play
this role: a sub-field request such as `field(uniqueId)` on the NDPluginPva record never
receives an update (QSRV records do), and with the full request it spends seconds
formatting each frame as text.

**Memory rule.** RSS growth during a run is compared after subtracting the array pool's
growth (`PoolUsedMem` before → peak), because pool buffers are never returned below
`maxMemory`; what remains must stay under 50 MB. Starting a continuous acquisition
allocates ~256 MB once (SDK transfer buffers, released at stop), so the `long` group
measures leak from its first sample onward and records that start-up allocation separately.

**Incomplete runs.** If the camera has finished its `NumImages` and the writer has stopped
short of `NumCapture`, frames were dropped at a plugin queue; the runner closes the file and
the drop/captured assertions report the numbers instead of a "stall".

**Frame-interval bound.** `NDArrayTimeStamp` is the SDK's arrival time and the SDK delivers
in bulk transfers below ~1024 rows, so "no interval above 2× nominal" is asserted only at
1024 rows and above; below that the bound is `max(2× nominal, 150 ms)`, a stall detector.

**Records.** Every session appends itself to `tests/.results/stress-<date>.json`
(`{"sessions": [{"meta", "runs", "extra"}, ...]}`, one `runs` row per streaming run,
`extra` for the long/cycles/load/provoke summaries); `--record` also writes a dated markdown
table into `info/performance/`, which is tracked: commit it deliberately, and note the driver
from its Conditions table if it was Damon's IOC.
