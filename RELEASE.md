ADAxisSXR40 Releases
====================

Change log for the EPICS areaDetector driver for the AXIS-SXR-40 detector
(Tucsen Dhyana XFXV4040BSI over USB).

Part of **DISCO** — Detector Interface for Streaming, Control, and Open-source
integration. Licensed under the LBNL BSD variant; see [LICENSE](LICENSE), which
also retains the areaDetector notice this module is obliged to carry.

### Why porting from ADTucsen was safe

ADTucsen bundles an **older copy of the same SDK** — 4.0 MB / 65 functions /
951-line `TUDefine.h`, against our 5.7 MB / 89 / 1309. Both share SONAME
`libTUCam.so.1` and both carry `CTUDrvCypress`, the Cypress FX3 **USB** backend,
with libusb statically linked. The ActiveSilicon frame-grabber backend was added
later, which is why only the newer library needs `libphxapi` — ours is a superset,
not a divergence. Its test cameras (Dhyana 400BSI `E408`, 400D `6404`/`E404`) are
all in our own `sdk/tuusb.conf` USB allow-list, so the transport is analogous.

Two checks decided it:

- All **74** `TUCAM_*` / `TUID*` symbols `tucsen.cpp` references exist in our
  headers — no missing API.
- Of the **37** enum constants it uses, **zero changed numeric value** between the
  two SDK versions. That was the real risk: a silently renumbered id would have
  had the driver talking to the wrong control.

Upstream's bundled `tucsenSupport/os/**` binaries and old headers were deleted so
they cannot shadow the installed SDK; `CONFIG_SITE` sets
`TUCAM_EXTERNAL = YES` to link the system-installed `libTUCam` instead.

R0-1 (unreleased)
-----------------

First working build. Compiles clean against EPICS Base 7.0.10, areaDetector
R3-14 and asyn R4-45 on Ubuntu 26.04 / GCC 15.2. **Not yet run against the
camera.**

Seven changes from upstream ADTucsen, each driven by a measured property of this
camera (see `info/camera/dhyana-xfxv4040bsi.md`):

1. `TUCAM_Buf_WaitForFrame` is given an explicit `exposure + 3000 ms` timeout.
   Upstream relied on the header default of 1000 ms, so every exposure past ~1 s
   failed — and this camera's range reaches 3600 s.
2. Frame data is copied row by row via `uiWidthStep` instead of one flat
   `memcpy`, with a contiguous fast path.
3. The 8 parameters this camera does not implement are **kept** in the driver and
   the `.template`, not pruned. Their controls are off both `medm` screens, but the
   records stay: they are harmless, removing them would fork the parameter set away
   from upstream for no functional gain, and `reportCapabilitySupport()` is the
   authoritative statement of what the camera implements — a list that is generated
   from the hardware at every boot cannot go stale the way a hand-pruned database
   can. See Known gaps in `info/known-gaps/README.md`.
4. Added `AXIS_TEC_ENABLE`, `AXIS_BUFF_FRAMES`, `AXIS_BUFF_TOTAL`. The SDK ring
   is only 2 frames deep, so ring occupancy is the dropped-frame early warning.
5. Fixed the text-info calling convention: `TUCAM_VALUE_INFO.pText` must be
   `NULL` so the SDK can return a pointer to its own string. Upstream passed a
   caller buffer, which returns SUCCESS and leaves it untouched — which is why
   `ADModel`, `ADSDKVersion` and `ADFirmwareVersion` were blank.
6. Fixed a copy-paste bug in the ROI height clamp, which wrote the clamped
   height into `ADSizeX`.
7. ROI values are aligned down before being handed to the SDK. Unaligned values
   were silently rounded by the camera, so the readback disagreed with the request.
   The requirement is **asymmetric**: width to a multiple of **8**, height and both
   offsets to a multiple of **4**. Aligning width to 4 — which is what upstream and
   the vendor's own GUI (`((v >> 2) << 2)`) do — is too permissive and leaves the
   camera silently narrowing half of all valid-looking width requests. Measured
   2026-07-29; full evidence in
   `info/porting/differences-from-adtucsen.md`.

Also added `reportCapabilitySupport()`, which probes every id the driver drives
at connect and logs what this camera actually implements — 8 of the 26 ids
inherited from upstream are unimplemented here, and an unsupported *Set* in this
SDK fails silently.

IOC geometry corrected to 4096 × 4096 with `NELEMENTS=16777216`; upstream's
5,600,000 was sized for a 2048² sensor.

8. The real `libjpeg`/`libtiff`/`libpng` are linked directly into the IOC
   executable so they outrank `libTUCam.so.1`, which statically bundles all
   three plus zlib and exports every one of their symbols. Without it
   `NDFileJPEGConfigure` in `commonPlugins.cmd` segfaults inside TUCam's
   `jpeg_CreateCompress` before `iocInit` is reached, and TIFF/PNG writing would
   bind to the wrong copies too. Mechanism documented in
   `iocs/axisSXR40IOC/axisSXR40App/src/Makefile`.

The two divergent startup files were reconciled into a single `st.cmd`. The
corrected geometry had lived only in `st.cmd.linux`, which nothing launched
(`start_epics.sh` runs `st.cmd`) and which could not have run anyway: it sourced
a nonexistent `envPaths.linux`, loaded `$(AREA_DETECTOR)/ADApp/Db/ADBase.template`
in the pre-R3 layout, and read `../commonPlugins.cmd` instead of
`$(ADCORE)/iocBoot/commonPlugins.cmd`. Its `axisSXR40Config` call also passed 7
arguments against upstream's mis-documented signature, landing a stray `10` in
`stackSize`. Added the `auto_settings.req` and `autosave/` directory that
`commonPlugins.cmd` and `create_monitor_set` require and that were both missing.

**First IOC start against the camera.** The camera enumerates as
`Dhyana XF/XV4040BSI` at 289.5 MB/s, `reportCapabilitySupport()` reports 11/15
capabilities and 8/12 properties, every plugin loads and `iocInit` completes.

**13. The NDArrayPool is bounded.** `st.cmd` passed `maxMemory = 0` (unlimited).
At 32 MiB per frame a stalled plugin accumulates at ~288 MB/s, so on a 15 GB host
that reaches the OOM killer in under a minute and takes the IOC with it. Now capped
at **1.5 GiB** (48 frames, ~5 s of full-rate acquisition).

Since ADCore R3-3 this single number bounds the driver *and every downstream plugin*
together, because plugins allocate from the driver's pool rather than their own — so
it is the right lever. `maxBuffers` is passed as 0 because R3-3 and later ignore it
entirely; there is no limit on array count any more, only on total memory.

Verified by capping the pool at 64 MiB and letting `NDPluginCircularBuff` retain
frames until it was exhausted:

| | |
|---|---|
| `PoolUsedMem` | 64 MB — exactly the cap |
| `DetectorState_RBV` | `Error`, acquisition stopped |
| `StatusMessage_RBV` | `NDArrayPool out of memory (maxMemory cap)` |
| IOC | stayed up; resumed normally once the retaining plugin was disabled (53 frames) |

Two diagnostics were fixed along the way, because the failure was hard to read:
the log now reports the actual numbers (`pool 64 MB of 64 MB, 2 buffers`) instead of
upstream's "not enough buffers left" — which pointed at a buffer count that no longer
exists — and `imageGrabTask` no longer overwrites that specific status message with
the generic "Failed to get image".

Note for anyone checking the cap: `$(P)$(R)PoolMaxMem` is `SCAN="Passive"` with
`PINI="YES"` in ADCore's `NDArrayBase.template`, so it latches 0 at `iocInit` and
never updates. It reads correctly only after
`caput …PoolPollStats 1` followed by `caput …PoolMaxMem.PROC 1`. `PoolUsedMem` and
`PoolAllocBuffers` are `I/O Intr` and do track live.

**14. The padded-buffer copy is no longer dead code, and RGB888 is withdrawn.**

`grabImage`'s size check compared the *unpadded* size against the SDK's `uiImgSize`
and aborted on any difference — which made the row-by-row copy (change 2)
unreachable, since a padded buffer is exactly what failed that check. The two pieces
contradicted each other. The check now also accepts `nRows * uiWidthStep`, and
*only* that; anything else still aborts. The row copy is therefore enabled only when
the SDK's own reported size confirms the stride model, which is precisely the
condition under which that copy is correct — a wrong guess cannot silently shear an
image, it fails the equality and aborts as before. If it ever does engage it logs
that this is the first observation on this camera and that the path is unverified.

Evidence that padding is unreachable here, gathered 2026-07-29: the size check has
never fired across full frame, 2×2 and 4×4 binning, and ROIs with deliberately
awkward row byte counts (2000, 1584, 2160, 1200); `TUIDC_BITOFDEPTH` offers only 16;
and ROI width must be a multiple of 8, so `rowBytes` is always a multiple of 16.
The padded path consequently remains unexecuted — reachable in principle rather than
dead by construction.

**`RGB888` removed from `FrameFormat`.** Found while hunting for a padding mode: on
this mono sensor, selecting it makes `TUCAM_Buf_WaitForFrame` return
`TUCAMRET_NOT_SUPPORT` and acquisition stop — and setting the format back to `Raw`
does **not** recover it, because the format is applied at `Buf_Alloc`. The capture
has to be stopped and restarted, and the camera took some settling before frames
flowed again. A menu entry that stalls the detector is a trap, so it is gone from
both `frameFormats[]` and the template's `mbbo`/`mbbi` states, and `writeInt32` now
range-checks the value so a stale autosave entry of 2 is rejected rather than acted
on. `Raw` and `Usual` are bit-identical here, so nothing is lost.

Frame rate versus ROI height — measured
---------------------------------------

> Method, the traps involved, and a re-runnable script:
> [info/performance/](info/performance/). Full conditions and analysis:
> [info/performance/2026-07-29-roi-frame-rate-physical.md](info/performance/2026-07-29-roi-frame-rate-physical.md).
> The same sweep on a KVM guest, one document per USB controller:
> [info/performance/2026-08-25-roi-frame-rate-vm-asmedia-bl1101ad01.md](info/performance/2026-08-25-roi-frame-rate-vm-asmedia-bl1101ad01.md) (ASMedia, the
> configuration that deadlocked) and
> [info/performance/2026-08-26-roi-frame-rate-vm-renesas-bl1101ad01.md](info/performance/2026-08-26-roi-frame-rate-vm-renesas-bl1101ad01.md) (Renesas — clean, and
> at bare-metal speed). Physical versus VM, side by side:
> [info/performance/comparison.md](info/performance/comparison.md).
> **Caveat (2026-08-26):** the frames behind the VM figures turned out to be a
> camera-generated test ramp, not sensor data — rates and loss counts stand, image
> content does not; see [info/known-gaps/TODO.md](info/known-gaps/TODO.md) §8.

The AXIS test report §3.1 tabulates frame rate against ROI height at full width.
Checked against this IOC on 2026-07-29 in continuous mode at 20.64 µs exposure, so
exposure never limits. "Acquire only" has `ArrayCallbacks` disabled; "Acquire +
HDF5 write" has the full `commonPlugins.cmd` chain active and NDFileHDF5 streaming
uncompressed to the host NVMe (which itself does 1.7 GB/s, ~6x the camera).

| ROI (W × H) | Frame | Vendor (Hz) | Acquire only (fps) | % of vendor | Acquire + HDF5 write (fps) | Write rate | Cost of writing |
|---|---|---|---|---|---|---|---|
| 4096 × 4096 | 33.6 MB | 9 | **8.6** | 96 % | **8.2** | 277 MB/s | −4.7 % |
| 4096 × 2048 | 16.8 MB | 19 | **17.4** | 92 % | **16.9** | 284 MB/s | −2.9 % |
| 4096 × 1024 | 8.4 MB | 38 | **34.7** | 91 % | **33.4** | 281 MB/s | −3.7 % |
| 4096 × 512 | 4.2 MB | 75 | **69.2** | 92 % | **66.9** | 280 MB/s | −3.3 % |
| 4096 × 256 | 2.1 MB | 150 | **137.6** | 92 % | **133.8** | 281 MB/s | −2.8 % |
| 4096 × 128 | 1.0 MB | 297 | **273.3** | 92 % | **263.4** | 276 MB/s | −3.6 % |
| 4096 × 64 | 524 kB | 583 | **537.1** | 92 % | **501.8** | 263 MB/s | −6.6 % |
| 4096 × 32 | 262 kB | 1126 | **1039.6** | 92 % | **1004.0** | 263 MB/s | −3.4 % |
| 4096 × 8 | 66 kB | 3726 | **3540.1** | 95 % | **3244.5** | 213 MB/s | −8.4 % |

**Nothing was dropped in any run**, at any height, with or without writing.

Three things this establishes:

- **The vendor's figures are achievable.** Acquisition lands at a strikingly
  consistent **~92 %** of their number across three orders of magnitude — a
  systematic offset, not scatter. Most likely their figures come from the SDK's own
  live-mode timing while these are counted from `ArrayCounter_RBV` over a wall
  clock, which includes this driver's per-frame work.
- **Writing to disk costs almost nothing** — 3 to 5 % up to 1000 fps, rising to
  8 % only at 3244 fps where per-frame overhead dominates. The camera is the limit,
  not the storage or the plugin chain.
- **Sustained throughput sits at 263–284 MB/s** across almost the whole range, which
  is the USB 3.0 ceiling (~289 MB/s measured). Only 4096 × 8 falls below it, at
  213 MB/s, because at 3244 fps the fixed cost per frame bites before the bandwidth
  does.

The inverse-height law holds: `fps × height` ≈ 35 000 rows/s from 4096 rows down to
128, tailing off to 28 300 at 8 rows. **Only height buys speed** — the vendor's
table holds width at 4096 throughout, consistent with a rolling shutter reading row
by row.

Notes on file writing
---------------------

The per-height numbers are in the table above. Two things are worth knowing before
relying on them, both of which cost time to work out:

- **Stream mode fixes the frame geometry when `Capture` starts**, using the
  dimensions of the last array the plugin saw — not the current ROI. Change the ROI
  and start `Capture` without acquiring a frame in between and every frame is
  rejected with `"Invalid frame. Ignoring."`, `NumCaptured` stays 0, and you are left
  with a 100-byte file. The detector reports no error at all. Acquire one frame at
  the new geometry first.
- **Short runs badly understate the rate.** 30 full frames measured 6.4 fps against
  8.2 fps for 90, because file open and close are a fixed cost amortised over fewer
  frames. Benchmark with enough frames to swamp it.

Files were verified rather than trusted: read back with an independent HDF5 build,
they carry the expected shapes — `[90 x 4096 x 4096]`, `[400 x 256 x 4096]`,
`[10000 x 8 x 4096]` — and sizes match frames x width x height x 2 exactly.

Note the scratch/tmp filesystem on this host is **tmpfs**, i.e. RAM. Benchmarking
file writing there measures memory bandwidth (3.7 GB/s), not storage.

Verified against the camera
---------------------------

Measured 2026-07-29 on AXIS s/n 702 / camera KBSG09024003, Ubuntu 26.04:

| | |
|---|---|
| Enumeration | `Dhyana XF/XV4040BSI`, SDK `2.0.7.0`, firmware `2c022311292c01220509`, 289.5 MB/s |
| Capability audit | 11/15 capabilities, 8/12 properties |
| Single frame | `ArraySize` = 33554432 (32 MiB exactly), stats min 206 / max 29251 / mean 1548.9 — `Total ÷ mean` = 16777216, so the full frame arrives untruncated |
| Exposure quantisation | 0.05 s requested → 0.0500004 read back, a multiple of the 10.32 µs row time |
| Continuous | ~9 fps at full frame (≈8.6 predicted), 0 dropped; ~80 fps at 1000×600, 0 dropped |
| Binning | 2048² and 1024² both acquire and write; mean scales by exactly the bin factor² (1548.9 → 6195.3 → 24799.3), which is what charge summing must do |
| ROI | unaligned 102/66/1002/998 applied and reported as 100/64/1000/996; `ArraySize` = 1992000 exact |
| TIFF | 4096×4096, `BitsPerSample` 16, 1 sample/pixel, uncompressed — structurally verified |
| HDF5 | valid container; with `Compression=zlib, ZLevel=6` 32 MB → 23.7 MB and re-read cleanly by an independent HDF5 build (`filters=1 [deflate lvl=6]`, mean matching) |
| Software trigger | gates correctly — 0 frames until triggered, then exactly 1 per trigger |
| Trigger out | mode/edge/delay/width round-trip on all 3 ports |
| Sensor temperature | raw −9.05 → **−0.49 °C** via this unit's factory calibration |
| Errors at `iocInit` | 0 `recGblRecordError`, 0 segfaults; 8 capability-write errors across the 4 ids the vendor marks unsupported |

Not verified: external trigger-in (needs a pulse generator), trigger-out pulses on a
scope, and the TEC (needs the water loop — see the hazard note at the call site).

**9. `axisSXR40.template` parameter names brought back in step with the driver.**
The port from ADTucsen renamed every parameter from `T_*` to `AXIS_*`, but the
template kept the old names — so 80 record fields referenced parameters that do
not exist and **42 of the 45 camera parameters were inert**. Every camera-specific
control silently did nothing; the IOC logged 80 ×
`asynPortDriver:drvUserCreate: cannot find parameter T_…` and 16 ×
`ao: init_record Error (514,11)` at every boot. Only `ADBase.template` records
worked, which is why model, geometry and temperature read correctly and hid it.

The rename mapping was confirmed 1:1 in both directions before changing anything:
strip the prefixes and the template's 45 references and the driver's 45 `#define`s
are the same set, nothing left over either way. Afterwards: zero
`cannot find parameter`, zero `ao init_record` errors, zero `recGblRecordError`,
and readbacks carry SDK-populated enum labels (`BinMode_RBV` = `4096x4096`,
`FanGear_RBV` = `High`, `Bus_RBV` = `USB3.0`), confirming `readEnum` /
`getCapabilityText` work against the hardware.

**10. Records added for the three parameters change 4 introduced.**
`AXIS_TEC_ENABLE`, `AXIS_BUFF_FRAMES` and `AXIS_BUFF_TOTAL` had `createParam`
calls but no records and no widgets, so the TEC control and the dropped-frame
telemetry were unreachable from EPICS despite being listed as delivered.
`TECEnable`/`TECEnable_RBV` are an mbbo/mbbi pair beside `FanGear`; the two
counters are `longin`. `BuffTotal_RBV` reads **2** from the camera, confirming the
documented SDK ring depth over EPICS for the first time.

OPI widgets have since been added to the `medm` `.adl` screens, alongside removing
the 8 unsupported controls. The `caQtDM` `.ui` files are still stale — they are
generated, and regenerating them needs `adl2ui`, which is not installed on this
host. See Known gaps.

Supporting work in the parent repository: `../CameraProbe` (read + capture path)
and `../ControlProbe` (the write/control path — all 26 SDK calls this driver
makes are verified working on the camera).

**11. All four SDK handles are now zero-initialised.** `frameHandle_`,
`triggerHandle_`, `triggerOutHandle_` and `camHandle_` were plain members with no
`memset` and no constructor initialisation, yet each has `[in]` fields the SDK
reads. The visible consequence was `TUCAM_FRAME.uiRsdSize` — documented as "how
many frames do you want" and read by `TUCAM_Buf_Alloc` — being passed indeterminate
memory on every acquisition start.

Note that *setting* `uiRsdSize` is not the fix it appears to be: requesting 8 frames
left the SDK still reporting `Can get 2 frames!` and then killed the IOC with
`double free or corruption (out)`. Ring depth is effectively fixed at 2 in SDK
2.0.7.0.

**12. Documented against the vendor manuals.** Four manuals were converted to
Markdown -- the two AXIS ones in `info/manuals/` here, the two Tucsen SDK ones in
the support repository's `info/manuals/` -- and resolved several
standing unknowns, each now recorded at the relevant call site rather than only in
a notes file:

- `TUIDP_TEMPERATURE` carries **different quantities in each direction** — a
  `[0, 100]` setpoint with a −50 offset on write, and an uncalibrated measured
  value on read (real °C ≈ `1.7 × value + 15`, AXIS test report p10). The read
  returned −9.05, outside `[0, 100]`, which proves the scales differ.
  `TemperatureActual` now carries `EGU="raw"`, overriding ADBase's `"C"`.
- The **TEC is water cooled** and a supply failure risks permanent sensor damage;
  `ENABLETEC` is additionally marked unsupported for this model in the vendor
  table despite passing the runtime audit.
- `uiRsdSize` is **frames-per-fetch**, not ring depth — now set to 1, the
  documented value. Change 11 is what exposed it.
- `TUIDC_ATLEVELS` and `TUIDC_FLTCORRECTION` are **4-state**, not enables, and
  the latter is a build-then-apply sequence. This explains the
  `TUCAMRET_NO_RESOURCE` write failures.
- `TUCAMRET_NOT_SUPPORT` (0x80000312) versus `TUCAMRET_NO_RESOURCE` (0x80000102)
  cleanly separates "absent" from "precondition unmet"; `setCapability()` now
  documents the split and which ids fall where.
- The API guide states ROI fields must be multiples of **4**, including width —
  which this camera contradicts, confirming the measured width-8 rule as an
  undocumented divergence rather than a misreading.
