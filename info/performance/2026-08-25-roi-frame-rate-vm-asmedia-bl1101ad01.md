# Frame rate versus ROI height — VM `bl1101ad01`, ASMedia ASM2142 USB controller, 2026-08-25

The ROI frame-rate sweep run on `bl1101ad01`, a Proxmox/KVM virtual machine, with the
detector on an **ASMedia ASM2142** USB 3.1 PCIe card passed through to the guest.
Method and traps: [README.md](README.md). This document holds this configuration's
measurements only; how it compares with the physical host and with the Renesas
controller is in [comparison.md](comparison.md).

**Status: acquire-only complete (all nine heights, three independent runs).
Acquire + HDF5 write: five of nine heights, 4096 → 256 rows.** Both write attempts
were ended by the stop deadlock described in [../stop-deadlock.md](../incidents/stop-deadlock.md)
— which this sweep is what found — the second at the 128-row stop, so 128 → 8 rows
have no write measurement in this configuration. This configuration was retired the
same afternoon; the detector now runs on a different controller.

## Conditions

| | |
|---|---|
| Detector / camera | AXIS s/n 702, camera `KBSG09024003`, SDK 2.0.7.0, firmware `2c022311292c01220509` |
| Host | AMD EPYC 9124, 8 vCPUs, 15 GB, KVM guest (Proxmox) |
| USB controller | ASMedia ASM2142 (`1b21:2142`), PCI passthrough (VFIO) to the guest, driver `xhci_hcd` |
| Camera path | fiber → VL813 hub → controller (`usb 10-2.2`) |
| SDK-reported USB transfer rate at connect | 265 |
| Storage | QEMU virtual disk (512 GB), ext4, 430 MB/s write (`dd` 2 GB, `oflag=direct`), 1.5 GB/s read |
| OS / kernel | Debian 13, 6.12.101+deb13-amd64 |
| Software | EPICS 7.0.10, ADCore R3-14, ADSupport R1-10, asyn R4-46, GCC 14.2 |
| Driver | ADAxisSXR40 R0-1 plus the uncommitted 2026-08-24/25 fixes |
| Plugins receiving frames in write mode | `HDF1` only — every other plugin `EnableCallbacks = Disable` |
| Width / exposure / trigger | 4096 / 20.64 µs / Free Run, continuous |
| Output directory | `/home/$USER/axis-perf-tmp` on the virtual disk (`/tmp` is tmpfs, 7.8 GB — not used) |

## Results — acquire only

`ArrayCallbacks` disabled; camera + driver, no plugins. Counted from
`ArrayCounter_RBV` over a 4.04 s wall clock after 1 s of settling.

| ROI (W × H) | Frame | Vendor (Hz) | **Measured (fps)** | Measured / vendor | MB/s | Repeat |
|---|---|---|---|---|---|---|
| 4096 × 4096 | 33.6 MB | 9 | **8.2** | 91 % | 274 | 8.2 |
| 4096 × 2048 | 16.8 MB | 19 | **16.3** | 86 % | 274 | 16.1 |
| 4096 × 1024 | 8.4 MB | 38 | **32.9** | 87 % | 276 | 32.2 |
| 4096 × 512 | 4.2 MB | 75 | **65.6** | 87 % | 275 | 63.9 |
| 4096 × 256 | 2.1 MB | 150 | **128.2** | 85 % | 269 | 124.8 |
| 4096 × 128 | 1.0 MB | 297 | **240.9** | 81 % | 253 | 235.4 |
| 4096 × 64 | 524 kB | 583 | **431.5** | 74 % | 226 | 420.6 |
| 4096 × 32 | 262 kB | 1126 | **861.0** | 76 % | 226 | 846.4 |
| 4096 × 8 | 66 kB | 3726 | **1511.0** | **41 %** | 99 | 1504.2 |

"Measured" is the complete post-reboot run (11:0x). "Repeat" is the same height from an
independent run in a different IOC session (the earlier partial sweep at 10:0x for
4096–32; a third session at 11:10 for 8). Agreement is within 1–4 %, tightest at
full frame. A third run at 13:23 (the write sweep's acquire-only legs) agreed again:
8.2, 16.6, 32.9, 65.8, 127.7, 240.6 fps for 4096 → 128.

### What it shows

**Frame rate falls further below the vendor figure the smaller the frame.** At full
frame the camera delivers 91 % of the datasheet rate; the ratio slides to 81 % at
128 rows, 74–76 % at 64 and 32 rows, and **41 % at 8 rows**.

**The cost is per frame, not per byte.** Throughput holds at 274–276 MB/s from 4096
down to 512 rows and only then falls — 253, 226, 226, 99 MB/s — as frames get small
and frequent. That is the signature of a fixed cost per USB transfer: at 1500 fps a
completion every 660 µs.

**The rows-per-second ceiling is not flat.**

| Height | 4096 | 2048 | 1024 | 512 | 256 | 128 | 64 | 32 | 8 |
|---|---|---|---|---|---|---|---|---|---|
| fps × height | 33 587 | 33 382 | 33 690 | 33 587 | 32 819 | 30 835 | 27 616 | 27 552 | 12 088 |

~33 600 rows/s down to 512 rows, sagging from 256 rows and down to a third at 8 rows.
**Planning rule for this configuration:** rates at 512 rows and above can be taken from
this table; anything smaller must be measured rather than assumed.

## Results — acquire + HDF5 write

`NDFileHDF5` streaming uncompressed to `/home` on the virtual disk, `HDF1` the only
plugin enabled. **End-to-end fps** is `NumCapture` divided by the wall clock from
`Acquire = 1` to `Capture = Done`, which includes camera start-up and the file close;
"vs acquire-only" is against the same-run acquire-only figure. Measured 2026-08-25
13:23.

| ROI (W × H) | Frames | **End-to-end (fps)** | Rate | vs acquire-only | Dropped |
|---|---|---|---|---|---|
| 4096 × 4096 | 90 | **7.9** | 264 MB/s | −3.7 % | 0 |
| 4096 × 2048 | 100 | **15.3** | 256 MB/s | −7.8 % | 0 |
| 4096 × 1024 | 200 | **30.5** | 256 MB/s | −7.3 % | 0 |
| 4096 × 512 | 400 | **61.2** | 257 MB/s | −7.0 % | 0 |
| 4096 × 256 | 800 | **122.3** | 256 MB/s | −4.2 % | 0 |
| 4096 × 128 | — | *not measured* | | | |
| 4096 × 64 | — | *not measured* | | | |
| 4096 × 32 | — | *not measured* | | | |
| 4096 × 8 | — | *not measured* | | | |

Every capture reached its full `NumCapture`; `HDF1:DroppedArrays_RBV` stayed 0
throughout; file sizes were exact — 3019.9, 1677.8, 1677.8, 1677.9, 1678.0 MB =
frames × 4096 × height × 2 plus HDF5 metadata.

### What it shows

**Writing cost 4–8 % end to end and dropped nothing** at every measured height. Note
that the end-to-end figure includes a fixed ~1.5–2 s per capture (camera start-up and
closing a 1.7–3 GB file), which over a 6–11 s run is most of that 4–8 %; it should
not be read as a per-frame write cost or as a storage throughput ceiling. The plugin
queue (`QSIZE = 21`, pool 1.5 GiB) absorbed whatever transient backlog occurred. The
runs are 6–11 s long; sustained behaviour over minutes is untested.

## What happened to the write attempts

The sweep runner started at 8 rows (deliberately, on a fresh camera). Acquire-only
measured 1504 fps; the `Acquire=0` that ended it **deadlocked the IOC** — the
`TUCAM_Cap_Stop` hang under the asyn port lock described in
[../stop-deadlock.md](../incidents/stop-deadlock.md). From then on no write reached the
driver: the HDF5 prime "passed" on a stale readback, `Capture` failed with
`must collect an array to get dimensions first`, and every later height failed
`SizeY did not take`. Nothing was wrong with the camera, the ROI or the plugin.

The same deadlock had already ended both earlier acquire-only sessions, each time
after the stop at 32 rows — which is why the two complete runs above exist in two
different IOC sessions. Tally across this day's sweeps in this configuration, by the
height being acquired when the stop was issued:

| Height | Stops | Deadlocked |
|---|---|---|
| 4096 … 256 (5 heights) | 20 | 0 |
| 128 | 3 | 1 |
| 64 | 2 | 0 |
| 32 | 2 | 2 |
| 8 | 2 | 1 |
| 32, temperature poll disabled | 1 | 1 |
| upstream ADTucsen IOC, 32 | 1 | 1 |

Consequences for the method, now in the script: it checks that `DetectorState_RBV`
leaves `Acquire` after every stop and exits 2 on a deadlock, the prime step requires
`ArrayCounter_RBV` to advance rather than trusting `ArraySizeY_RBV`, and after every
stop it proves the driver is alive with a write that must round-trip.

The second write attempt ran the heights safest-first and produced the five write
points above before deadlocking at the **128-row** stop (13:25) — a height that had
survived its two previous stops. This one had a different shape: `Cap_Stop` returned,
the image task went idle, and the *temperature poll* then hung in a USB control
transfer while holding the port lock (`DetectorState_RBV` read `Idle`). The write
round-trip check caught it at the point that caused it, so nothing measured was lost.
There was evidently no safe threshold, only a probability that rose with frame rate. A
further session with the temperature poll disabled (`AXIS_NO_TEMP_POLL=1`) deadlocked
on the *exposure write* after its first 32-row stop — the poll is a victim, not the
cause ([../stop-deadlock.md](../incidents/stop-deadlock.md)). The kernel logged
`xhci_hcd: ERROR Transfer event TRB DMA ptr not part of current TD` on the frame-data
endpoint at every fast stop in this configuration, deadlocking or not.

## Four things specific to this host

- **`/tmp` is tmpfs, 7.8 GB.** Not just a benchmarking trap (README thing 4) — a
  reboot wipes it. Two reboots during this session took the raw result files with
  them; the numbers above were recovered from terminal output. Keep results under
  `/home`.
- **Recovery from a deadlocked IOC is a VM reboot, not a detector power cycle.**
  `SIGKILL` of a deadlocked IOC leaves the camera enumerated but unclaimable (3 of 3
  — though in every case the camera had *already* stopped answering, which is what
  hung the SDK, so the kill may not be what wedges it); a USB device `unbind`/`bind`
  restores descriptor reads but not the interface claim (1 of 1); an xhci
  **controller** `unbind`/`bind` (`0000:01:00.0`) also restores descriptor reads, but
  the next IOC start hangs in the camera open and the device stops answering again
  (1 of 1); rebooting the guest re-initialises the passed-through controller and
  recovered it fully every time (6 of 6). The detector was never power-cycled on
  2026-08-25.
- **Another IOC auto-starts at boot** (`ioc-xv4040.service`, the ADTucsen-based
  one) and takes the camera. `sudo systemctl stop ioc-xv4040` before every run.
- **The camera's USB bus number changes across reboots** (`Bus 010` one boot,
  `Bus 003` the next) — probe order among one passed-through and nine virtual
  controllers. Harmless to the SDK, which finds the camera by id, and unrelated to
  the deadlock. But never script against `/dev/bus/usb/<bus>/…` or a `<bus>-<port>`
  sysfs path here; use `lsusb -d 5453:e41b`.

## Not covered

- **Write mode at 128 → 8 rows** — never measured in this configuration; the
  configuration was retired before it could be.
- **Pixel content** — never inspected; the files were deleted before the 2026-08-26
  finding that the camera was delivering a test ramp instead of sensor data (see the
  Renesas document, "Data content"). Whether it already was on 2026-08-25 is unknown.
- **Sustained runs** — the longest capture here is 11 s.
- Compression, width scaling, binned modes, other storage.
