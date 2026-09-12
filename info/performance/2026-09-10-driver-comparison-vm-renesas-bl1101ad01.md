# 2026-09-10 — ADAxisSXR40 vs ADTucsen, same host, same hour

Same VM (`bl1101ad01`, KVM guest), same Renesas uPD720202 USB controller via passthrough,
same camera (`KBSG09024003`, SDK 2.0.7.0), same `roi-rate-test.sh`, same prefix `XV4040:`.
The two IOCs were swapped with `systemctl` (`ioc-axissxr40` ↔ `ioc-xv4040`) and each run
within about 15 minutes of the other. Both drivers passed every point; neither deadlocked
at any stop, including 32 and 8 rows.

## Acquire-only (4 s window, `ArrayCallbacks` off)

| Height | ADAxisSXR40 fps | ADTucsen fps | ADAxisSXR40 MB/s | ADTucsen MB/s |
|---|---|---|---|---|
| 4096 | 8.7 | 8.7 | 290 | 291 |
| 2048 | 17.3 | 17.3 | 291 | 291 |
| 1024 | 34.4 | 34.4 | 289 | 289 |
| 512 | 68.8 | 68.8 | 289 | 289 |
| 256 | 137.1 | 137.1 | 288 | 288 |
| 128 | 272.2 | 272.0 | 285 | 285 |
| 64 | 534.4 | 534.2 | 280 | 280 |
| 32 | 1037.4 | 1032.8 | 272 | 271 |
| 8 | 3577.5 | 3584.9 | 234 | 235 |

## Acquire + HDF5 stream (`h5check` on every file)

| Run | Driver | Written | Dropped | fps with writer | fps by camera timestamps | UniqueId |
|---|---|---|---|---|---|---|
| 4096 rows × 100 | ADAxisSXR40 | 100/100 | 0 | 8.2 | 8.6 | 1…100 contiguous |
| 4096 rows × 100 | ADTucsen | 100/100 | 0 | 8.2 | 8.6 | 1…100 contiguous |
| 32 rows × 2000 | ADAxisSXR40 | 2000/2000 | 0 | 905.7 | 1039.8 | 1…2000 contiguous |
| 32 rows × 2000 | ADTucsen | 2000/2000 | 0 | 905.5 | 1040.3 | 1…2000 contiguous |

## Reading

- **The data path is the SDK's, and it is the same in both drivers.** Every rate is
  within run-to-run noise (<0.5 %). Nothing in ADAxisSXR40's grab loop (timeout, row copy,
  ring telemetry) costs throughput, and nothing in it gains any.
- **Every frame from both drivers was the camera's synthetic ramp** (min 0, max 65280,
  mean 32640.0, 1/256 zeros), as first seen 2026-08-26. Same camera state under both
  drivers; a camera power-cycle is the next step, not software.
- What this comparison does **not** test: trigger modes, binning, TEC, the ROI alignment
  rule, the ROI height-clamp fix, the AutoLevels readback fix. Those are the driver-level
  differences listed in `../porting/ADAxisSXR40-vs-ADTucsen.md` §5 and need a functional
  test, not a rate test.
- ADTucsen's settings (ROI 4096×32, 1 ms exposure, HDF5 Single mode to `/data/xv4040`,
  `darkframe`) were snapshotted before and verified identical after; its autosave holds
  nothing from this run.
