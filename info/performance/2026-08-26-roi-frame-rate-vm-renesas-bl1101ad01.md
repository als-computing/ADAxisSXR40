# Frame rate versus ROI height — VM `bl1101ad01`, Renesas uPD720202 USB controller, 2026-08-26

The ROI frame-rate sweep run on `bl1101ad01`, a Proxmox/KVM virtual machine, with the
detector on a **Renesas uPD720202** USB 3.0 controller on the hypervisor motherboard,
passed through to the guest. Method and traps: [README.md](README.md). This document
holds this configuration's measurements only; how it compares with the physical host
and with the ASMedia controller is in [comparison.md](comparison.md).

**Status: complete.** All nine heights, both modes, one uninterrupted session
(13:48:57 → 13:51:58, 3 minutes). **Every capture reached its full frame count,
`DroppedArrays` was 0 at every height, every file was the exact expected size, and all
18 stops were clean.**

## Conditions

| | |
|---|---|
| Detector / camera | AXIS s/n 702, camera `KBSG09024003`, SDK 2.0.7.0, firmware `2c022311292c01220509` |
| Host | AMD EPYC 9124, 8 vCPUs, 15 GB, KVM guest (Proxmox) |
| USB controller | Renesas uPD720202 (`1912:0015`), on the hypervisor motherboard, PCI passthrough (VFIO) to the guest, driver `xhci-pci-renesas` |
| Camera path | fiber → VL813 hub → controller (`usb 10-2.2`) |
| SDK-reported USB transfer rate at connect | 285 |
| Storage | QEMU virtual disk (512 GB), ext4; `dd` 2 GB: 978–1000 MB/s `oflag=direct`, 715–848 MB/s buffered + `fsync` (varies run to run) |
| OS / kernel | Debian 13, 6.12.101+deb13-amd64 |
| Software | EPICS 7.0.10, ADCore R3-14, ADSupport R1-10, asyn R4-46, GCC 14.2 |
| Driver | ADAxisSXR40 R0-1 plus the uncommitted 2026-08-24/25 fixes |
| Plugins receiving frames in write mode | `HDF1` only — every other plugin `EnableCallbacks = Disable` |
| Width / exposure / trigger | 4096 / 20.64 µs / Free Run |
| Write mode | `ImageMode = Multiple`, `NumImages = NumCapture` (the camera acquires exactly the frames the file needs) |
| Output directory | `/home/$USER/axis-perf-tmp` on the virtual disk (`/tmp` is tmpfs, 7.8 GB — not used) |

## Results — acquire only

`ArrayCallbacks` disabled; camera + driver, no plugins. Counted from
`ArrayCounter_RBV` over a 4.04 s wall clock after 1 s of settling.

| ROI (W × H) | Frame | Vendor (Hz) | **Measured (fps)** | Measured / vendor | MB/s | Frames counted |
|---|---|---|---|---|---|---|
| 4096 × 4096 | 33.6 MB | 9 | **8.4** | 93 % | 282 | 34 |
| 4096 × 2048 | 16.8 MB | 19 | **17.1** | 90 % | 287 | 69 |
| 4096 × 1024 | 8.4 MB | 38 | **34.4** | 91 % | 289 | 139 |
| 4096 × 512 | 4.2 MB | 75 | **69.1** | 92 % | 290 | 279 |
| 4096 × 256 | 2.1 MB | 150 | **137.1** | 91 % | 288 | 554 |
| 4096 × 128 | 1.0 MB | 297 | **272.3** | 92 % | 285 | 1100 |
| 4096 × 64 | 524 kB | 583 | **534.4** | 92 % | 280 | 2159 |
| 4096 × 32 | 262 kB | 1126 | **1036.0** | 92 % | 272 | 4185 |
| 4096 × 8 | 66 kB | 3726 | **3567.9** | 96 % | 234 | 14416 |

At full frame only 34 frames fall in the 4.04 s window, so that figure is quantised
to ±0.25 fps. Repeatability on this controller (2026-08-25, same script): ten runs at
32 rows spanned 1035.9–1039.3 fps; ten at 8 rows 3559.5–3569.4 fps.

### What it shows

**The camera delivers 90–96 % of the vendor figure at every height**, and the ratio
does not fall as frames get smaller — 8 rows is the *best* point, not the worst.

**Throughput is flat at 280–290 MB/s from 4096 down to 64 rows**, 272 MB/s at 32 and
234 MB/s at 8 rows, against a USB 3.0 link that the SDK rated at 285 at connect. The
link, not the host, is the limit.

**The rows-per-second ceiling is flat.**

| Height | 4096 | 2048 | 1024 | 512 | 256 | 128 | 64 | 32 | 8 |
|---|---|---|---|---|---|---|---|---|---|
| fps × height | 34 406 | 35 021 | 35 226 | 35 379 | 35 098 | 34 854 | 34 202 | 33 152 | 28 543 |

~35 000 rows/s from 4096 to 64 rows, 33 000 at 32, 28 500 at 8. **Planning rule for
this configuration:** frame rate ≈ 35 000 / height for any height of 64 rows or more,
and this table for the rest.

## Results — acquire + HDF5 write

`NDFileHDF5` streaming uncompressed to the virtual disk, Stream mode, one frame per
chunk, `HDF1` the only plugin enabled. **End-to-end fps** is `NumCapture` divided by
the wall clock from `Acquire = 1` to `Capture = Done`; it includes camera start-up
and the file close. "vs acquire-only" is against the same-session acquire-only figure.

| ROI (W × H) | Frames | **End-to-end (fps)** | Rate | vs acquire-only | Captured | Dropped | File |
|---|---|---|---|---|---|---|---|
| 4096 × 4096 | 90 | **8.4** | 282 MB/s | 0 % | 90 / 90 | 0 | 3019.9 MB |
| 4096 × 2048 | 100 | **15.8** | 264 MB/s | −7.6 % | 100 / 100 | 0 | 1677.8 MB |
| 4096 × 1024 | 200 | **31.5** | 264 MB/s | −8.4 % | 200 / 200 | 0 | 1677.8 MB |
| 4096 × 512 | 400 | **62.9** | 264 MB/s | −9.0 % | 400 / 400 | 0 | 1677.9 MB |
| 4096 × 256 | 800 | **125.9** | 264 MB/s | −8.2 % | 800 / 800 | 0 | 1678.0 MB |
| 4096 × 128 | 1500 | **250.7** | 263 MB/s | −7.9 % | 1500 / 1500 | 0 | 1573.3 MB |
| 4096 × 64 | 3000 | **501.8** | 263 MB/s | −6.1 % | 3000 / 3000 | 0 | 1573.8 MB |
| 4096 × 32 | 6000 | **945.1** | 248 MB/s | −8.8 % | 6000 / 6000 | 0 | 1574.7 MB |
| 4096 × 8 | 10000 | **3254.6** | 213 MB/s | −8.8 % | 10000 / 10000 | 0 | 658.5 MB |

Every file size equals frames × 4096 × height × 2 plus HDF5 metadata.
`HDF1:DroppedArrays_RBV` was zeroed before each capture and read 0 after it.
`image1:DroppedArrays_RBV` stayed 0 throughout.

### What it shows

**Nothing is lost.** Nine captures, 22 090 frames, every one in its file.

**The 6–9 % end-to-end deficit is a fixed cost per capture, not a per-frame cost.**
Divide it out: each capture took 0.3–0.6 s longer than the frames alone would at the
acquire-only rate (2048 rows: 6.3 s for 100 frames against 5.85 s of camera time;
8 rows: 3.1 s for 10 000 frames against 2.8 s). That is camera start-up plus the time
to close a 0.7–3 GB file, and it is the same 0.3–0.6 s whether the run is 3 s or
10 s — so it is 9 % of a 6 s capture and would be under 1 % of a minute-long one. At
full frame the two figures coincide only because the 4096 acquire-only value is
quantised (see above). Instrumented runs on this controller (2026-08-26, camera,
plugin and file counters logged together) showed the writer one to two frames behind
the camera for the whole capture at 1024 and 256 rows, and a 900-frame, 27 s capture
at 1024 rows ran at 32.6 fps end to end with the plugin queue never above 37 of 150.

**Two PVs that look diagnostic are not.** `HDF1:IOSpeed` (1500–2100 MB/s here) times
only the `H5Dwrite` calls, and `HDF1:ExecutionTime` (0.03 ms) only the queueing
callback; neither measures the pipeline. Use the wall clock and the counters.

**Planning rule for this configuration, writing to its local disk:** the HDF5 writer
keeps pace with the camera at every height; budget ~0.5 s of overhead per capture,
which is negligible for anything longer than a few seconds.

## Data content — the frames are a test pattern, not sensor data

Checked after the sweep with [h5check.c](../../tools/h5check/h5check.c) (built against ADSupport's HDF5, so
not the IOC's own library). **Structure is exactly right in all nine files:** rank 3,
`frames × height × 4096`, `uint16`, one frame per chunk; `NDArrayUniqueId` runs 1 … N
with no gap or repeat; the camera timestamps inside each file give 8.6, 17.3, 34.5,
67.9, 135.3, 272.2, 534.2, 1037.2 and 3569.4 fps — the acquire-only rates, measured
independently of the script's wall clock. That also settles where the end-to-end
deficit comes from: the 2048-row file holds 5.73 s of camera time inside a 6.3 s
capture.

**The pixel values are not an image.** Every frame in every file — first, middle and
last — has min 0, max 65280, mean exactly 32640.0 and 1/256 of its pixels at zero: 256
distinct values, all multiples of 256 (an 8-bit ramp in the high byte), decreasing by
256 per column, shifting by 256 per row, with a different offset in every frame. Probes
taken afterwards at 50 ms, 1 s and 5 s exposure gave the identical ramp, so it is not
light and not exposure; `FrameFormat = Usual` gave the same ramp after the SDK's level
processing (two values: 33338, and 32195 at exactly the columns where the raw ramp is
zero). A real dark frame from this camera has a mean of ~68 ADU with sensor noise
([../dhyana-xfxv4040bsi.md](../camera/dhyana-xfxv4040bsi.md)). The camera was delivering a
synthetic pattern on 2026-08-26 — apparently a test-image or no-sensor-data mode of
its own; the SDK reports `TUIDC_TESTIMGMODE` as unsupported, so nothing in this
software can have switched it on, and nothing in this software can see it.

**Consequences.** Every frame here has the right size, arrives at the camera's real
rate and travels the same USB and HDF5 path as an image would, so the *rate* and
*loss* results stand. The *content* proves nothing about the sensor, and no run on
this VM before 2026-08-26 ever inspected pixel values, so it is unknown when the
pattern started. Until the camera has been power-cycled and a dark frame re-checked
(`h5check` on a single 50 ms frame should show a mean near 68 and noise, not 32640.0),
treat the detector as not imaging. Tracked in [../TODO.md](../known-gaps/TODO.md).

## Stops

Every point ends with `Acquire = 0` followed by a write that must round-trip through
the driver, which proves it is still alive ([README.md](README.md), thing 6). On this
controller:

| Session | Stops | Froze |
|---|---|---|
| 2026-08-25 — ten deliberate stops at 32 rows | 10 | 0 |
| 2026-08-25 — full sweep, both modes | 18 | 0 |
| 2026-08-25 — ten deliberate stops at 8 rows (3567 fps) | 10 | 0 |
| **2026-08-26 — this sweep, both modes** | **18** | **0** |
| Total | 56 | 0 |

The kernel logged nothing from `xhci` during any of them
(`~/axis-deadlock-evidence/dmesg-xhci-renesas.txt`, 2026-08-25). The freeze described
in [../stop-deadlock.md](../incidents/stop-deadlock.md) has not occurred on this controller.

## Two things specific to this host

- **`/tmp` is tmpfs, 7.8 GB, wiped at reboot.** Keep results and output under `/home`.
- **Another IOC auto-starts at boot** (`ioc-xv4040.service`, the ADTucsen-based one)
  and takes the camera. `sudo systemctl stop ioc-xv4040` before every run. The
  camera's USB bus number also changes across reboots; find it with
  `lsusb -d 5453:e41b`, never by bus/port path.

## Not covered

- **Sustained runs.** The longest capture in this sweep is 11 s (full frame); the
  longest on this controller 27 s (1024 rows, instrumented run). Minutes at full
  frame, where the virtual disk's write cache would fill, are untested.
- **One unexplained event, 2026-08-26.** One Multiple-mode run at 256 rows captured
  799 of 800 with nothing dropped and nothing logged; three repeats and this sweep all
  gave 800 / 800. The script now reports such a shortfall instead of waiting 60 s for
  it.
- Compression, width scaling, binned modes, other storage.
