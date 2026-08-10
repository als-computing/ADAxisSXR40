# Frame rate versus ROI height — measured 2026-07-29

First full sweep through the EPICS IOC, checking the AXIS test report §3.1 figures
and measuring what HDF5 streaming to disk costs on top.

Method and the traps involved: [README.md](README.md). Re-run with
[roi-rate-test.sh](roi-rate-test.sh).

## Conditions

| | |
|---|---|
| Detector | AXIS-SXR-40, AXIS s/n **702**, camera board **KBSG09024003** |
| Camera | Tucsen Dhyana XF/XV4040BSI, USB `5453:e41b`, SDK 2.0.7.0, firmware `2c022311292c01220509` |
| Host | Intel i7-8750H, 12 threads, 15 GB RAM, kernel 7.0.0-28-generic (Ubuntu 26.04) |
| Storage | Samsung SSD 960 EVO 1 TB NVMe, ext4 — **1.7 GB/s** sustained write, ~6x the camera |
| Software | EPICS Base 7.0.10, areaDetector R3-14, asyn R4-45, ADAxisSXR40 R0-1 |
| Width | 4096 throughout — only height varied, matching the vendor's table |
| Exposure | 20.64 µs (2 × the 10.32 µs sensor row time), so exposure never limits |
| Trigger | Free Run, continuous mode |
| Writing | `NDFileHDF5`, Stream mode, **uncompressed**, full `commonPlugins.cmd` chain active |
| Acquire-only | `ArrayCallbacks` disabled, so no plugin sees a frame |

## Results

| ROI (W × H) | Frame | Vendor (Hz) | Acquire only (fps) | % of vendor | Acquire + HDF5 write (fps) | Write rate | Cost of writing | Frames timed |
|---|---|---|---|---|---|---|---|---|
| 4096 × 4096 | 33.6 MB | 9 | **8.6** | 96 % | **8.2** | 277 MB/s | −4.7 % | 90 |
| 4096 × 2048 | 16.8 MB | 19 | **17.4** | 92 % | **16.9** | 284 MB/s | −2.9 % | 100 |
| 4096 × 1024 | 8.4 MB | 38 | **34.7** | 91 % | **33.4** | 281 MB/s | −3.7 % | 200 |
| 4096 × 512 | 4.2 MB | 75 | **69.2** | 92 % | **66.9** | 280 MB/s | −3.3 % | 400 |
| 4096 × 256 | 2.1 MB | 150 | **137.6** | 92 % | **133.8** | 281 MB/s | −2.8 % | 800 |
| 4096 × 128 | 1.0 MB | 297 | **273.3** | 92 % | **263.4** | 276 MB/s | −3.6 % | 1 500 |
| 4096 × 64 | 524 kB | 583 | **537.1** | 92 % | **501.8** | 263 MB/s | −6.6 % | 3 000 |
| 4096 × 32 | 262 kB | 1126 | **1039.6** | 92 % | **1004.0** | 263 MB/s | −3.4 % | 6 000 |
| 4096 × 8 | 66 kB | 3726 | **3540.1** | 95 % | **3244.5** | 213 MB/s | −8.4 % | 10 000 |

**Nothing was dropped in any run**, at any height, with or without writing.
`HDF1:DroppedArrays_RBV` and `image1:DroppedArrays_RBV` both stayed at 0 throughout,
and every capture reached its full `NumCapture`.

## What it shows

**The vendor's figures are achievable.** Acquisition sits at a strikingly consistent
**~92 %** of their number — seven of nine points, with the two extremes at 95–96 %.
That flatness matters more than the value: it is a fixed proportional overhead, not
something that degrades with rate, so any ROI can be planned at ~92 % of the
datasheet. The likeliest explanation is that their figures come from the SDK's own
live-mode timing while these are counted from EPICS over a wall clock, and so include
this driver's per-frame work. The two ends coming out slightly *better* is probably
rounding in their published integers (9 and 3726 bracket the table) — not worth
chasing unless someone needs the last few percent.

**Writing to disk is nearly free.** 3–5 % up to 1000 fps, reaching 8 % only at
3244 fps where per-frame overhead starts to dominate. This was the surprise: the
expectation going in was that file writing would be the wall, and it is not. The
camera is the limit, not the storage and not the plugin chain. Note the storage here
has ~6x headroom; on slower storage this conclusion will not hold, and the write
column is the one to re-measure.

**Throughput pins at 263–284 MB/s** across almost the whole range, which is the
USB 3.0 ceiling (~289 MB/s measured independently). Only 4096 × 8 falls below it, at
213 MB/s, for the same per-frame-cost reason.

**The inverse-height law holds.** `fps × height` ≈ 35 000 rows/s from 4096 rows down
to 128, tailing off to 28 300 at 8 rows as fixed per-frame cost begins to bite:

| Height | 4096 | 2048 | 1024 | 512 | 256 | 128 | 64 | 32 | 8 |
|---|---|---|---|---|---|---|---|---|---|
| fps × height | 35 226 | 35 635 | 35 533 | 35 430 | 35 226 | 34 982 | 34 374 | 33 267 | 28 320 |

**Only height buys speed.** The vendor's table holds width at 4096 throughout, which
is consistent with a rolling shutter reading row by row. A separate spot check at
1000 × 600 gave ~80 fps where 4096 × 600 would predict ~59, so narrowing the width is
not entirely without benefit — but height is the dominant term by a wide margin. If
you need speed, cut rows.

## Files were verified, not assumed

A clean `NumCaptured` only says the plugin believes it wrote everything. All three
files were read back with an HDF5 build independent of the IOC's and carry the
expected shapes:

| File | Dataset |
|---|---|
| `perf4096_000.h5` (3019.9 MB) | `[90 x 4096 x 4096]` |
| `perf256_000.h5` (839.0 MB) | `[400 x 256 x 4096]` |
| `perf8_000.h5` (658.5 MB) | `[10000 x 8 x 4096]` |

Sizes match `frames × width × height × 2` exactly, plus a little HDF5 metadata.

## Not covered

- **Compression.** Everything here is uncompressed. zlib at level 6 was verified
  working separately (32 MB → 23.7 MB on a full frame, reads back cleanly) but its
  cost at rate has not been measured, and it is CPU-bound rather than IO-bound so it
  will behave differently.
- **Width scaling.** Only the one 1000 × 600 spot check above; the sweep holds width
  at 4096.
- **Sustained runs.** The longest here is ~10 s. Thermal behaviour, and whether the
  NVMe holds 280 MB/s once its cache is exhausted, are untested.
- **Binned modes.** `TUIDC_RESOLUTION` 2×2 and 4×4 acquire correctly but were not
  rate-tested.
- **Other storage.** NVMe only. Network or spinning storage will change the write
  column and possibly the drop counts.
