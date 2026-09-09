# Comparison — the ROI frame-rate sweep on three configurations

The same sweep ([README.md](README.md); nine heights, both modes, 20.64 µs exposure,
4096 wide) has been run on three configurations. Each has its own results document
with only its own data; this file puts them side by side.

| | Physical host | VM, ASMedia | VM, Renesas |
|---|---|---|---|
| Document | [2026-07-29 physical](2026-07-29-roi-frame-rate-physical.md) | [2026-08-25 VM ASMedia](2026-08-25-roi-frame-rate-vm-asmedia-bl1101ad01.md) | [2026-08-26 VM Renesas](2026-08-26-roi-frame-rate-vm-renesas-bl1101ad01.md) |
| Host | Intel i7-8750H, 12 threads, 15 GB, bare metal | AMD EPYC 9124, 8 vCPUs, 15 GB, KVM guest `bl1101ad01` (Proxmox) | same VM |
| USB controller | on-board, direct | ASMedia ASM2142 `1b21:2142` on a PCIe card, VFIO passthrough, `xhci_hcd` | Renesas uPD720202 `1912:0015` on the hypervisor motherboard, VFIO passthrough, `xhci-pci-renesas` |
| SDK-reported USB rate at connect | 289.5 | 265 | 285 |
| Storage | Samsung 960 EVO NVMe, 1.7 GB/s write | QEMU virtual disk, 430 MB/s direct | same virtual disk (later `dd`: 978–1000 MB/s direct, 715–848 MB/s buffered + `fsync`) |
| OS / software | Ubuntu 26.04, kernel 7.0.0-28; EPICS 7.0.10, AD R3-14, asyn R4-45, GCC 15.2 | Debian 13, 6.12.101; EPICS 7.0.10, ADCore R3-14, ADSupport R1-10, asyn R4-46, GCC 14.2 | same as ASMedia |
| Driver | ADAxisSXR40 R0-1 | R0-1 + uncommitted 2026-08-24/25 fixes | same |
| Write-mode plugins | as configured then | `HDF1` only | `HDF1` only |
| Write-mode camera control | continuous, stopped after `Capture = Done` | continuous, stopped after `Capture = Done` | `ImageMode = Multiple`, `NumImages = NumCapture` |
| Detector, camera, SDK, firmware | AXIS s/n 702, `KBSG09024003`, SDK 2.0.7.0, fw `2c022311292c01220509` — identical in all three | | |

The only difference between the two VM configurations is the USB controller the
detector is plugged into.

## Acquire only

`ArrayCallbacks` disabled; `ArrayCounter_RBV` over 4.04 s after 1 s of settling.

| ROI (W × H) | Vendor (Hz) | Physical (fps) | VM ASMedia (fps) | VM Renesas (fps) | ASMedia / physical | Renesas / physical |
|---|---|---|---|---|---|---|
| 4096 × 4096 | 9 | 8.6 | 8.2 | 8.4 | 95 % | 98 % |
| 4096 × 2048 | 19 | 17.4 | 16.3 | 17.1 | 94 % | 98 % |
| 4096 × 1024 | 38 | 34.7 | 32.9 | 34.4 | 95 % | 99 % |
| 4096 × 512 | 75 | 69.2 | 65.6 | 69.1 | 95 % | 100 % |
| 4096 × 256 | 150 | 137.6 | 128.2 | 137.1 | 93 % | 100 % |
| 4096 × 128 | 297 | 273.3 | 240.9 | 272.3 | 88 % | 100 % |
| 4096 × 64 | 583 | 537.1 | 431.5 | 534.4 | 80 % | 99 % |
| 4096 × 32 | 1126 | 1039.6 | 861.0 | 1036.0 | 83 % | 100 % |
| 4096 × 8 | 3726 | 3540.1 | 1511.0 | 3567.9 | **43 %** | 101 % |

| | Physical | VM ASMedia | VM Renesas |
|---|---|---|---|
| Throughput, 4096 → 128 rows | 280–284 MB/s | 253–276 MB/s | 282–290 MB/s |
| `fps × height`, 4096 → 128 rows | ~35 200 rows/s, flat | 33 600 falling to 30 800 | ~35 000 rows/s, flat |
| `fps × height` at 8 rows | 28 300 | 12 100 | 28 500 |

**What it shows.** With the Renesas controller the VM acquires at bare-metal speed at
every height — within 2 % of the physical host from 8 fps to 3568 fps. The ASMedia
configuration was 5 % slower at full frame and 57 % slower at 8 rows, with a rate
collapse that began at 256 rows and had the signature of a per-transfer cost (flat
MB/s until frames got small and frequent, then a steep fall). That looked like a
virtualisation tax; it was not — same VM, same hypervisor, same passthrough, different
controller, and the tax is gone. **Virtualisation itself costs this detector nothing
measurable.**

## Acquire + HDF5 write

End-to-end fps = `NumCapture` / wall clock from `Acquire = 1` to `Capture = Done`;
"cost" = against the same-session acquire-only figure.

| ROI (W × H) | Frames | Physical (fps) | cost | VM ASMedia (fps) | cost | VM Renesas (fps) | cost | Renesas / physical |
|---|---|---|---|---|---|---|---|---|
| 4096 × 4096 | 90 | 8.2 | −4.7 % | 7.9 | −3.7 % | 8.4 | 0 % | 102 % |
| 4096 × 2048 | 100 | 16.9 | −2.9 % | 15.3 | −7.8 % | 15.8 | −7.6 % | 93 % |
| 4096 × 1024 | 200 | 33.4 | −3.7 % | 30.5 | −7.3 % | 31.5 | −8.4 % | 94 % |
| 4096 × 512 | 400 | 66.9 | −3.3 % | 61.2 | −7.0 % | 62.9 | −9.0 % | 94 % |
| 4096 × 256 | 800 | 133.8 | −2.8 % | 122.3 | −4.2 % | 125.9 | −8.2 % | 94 % |
| 4096 × 128 | 1500 | 263.4 | −3.6 % | — | | 250.7 | −7.9 % | 95 % |
| 4096 × 64 | 3000 | 501.8 | −6.6 % | — | | 501.8 | −6.1 % | 100 % |
| 4096 × 32 | 6000 | 1004.0 | −3.4 % | — | | 945.1 | −8.8 % | 94 % |
| 4096 × 8 | 10000 | 3244.5 | −8.4 % | — | | 3254.6 | −8.8 % | 100 % |

`DroppedArrays` was 0 at every measured point in all three configurations, every
capture reached its full count, and every file was the exact expected size. The
ASMedia write column stops at 256 rows because both of its write attempts were ended
by the stop deadlock (below).

**What it shows.** The writer keeps up with the camera in every configuration. The
end-to-end cost is a fixed per-capture overhead — camera start-up plus file close —
spread over a 3–11 s run: 0.2–0.4 s on the physical host's NVMe (3–5 %), 0.3–0.6 s on
the virtual disk (6–9 %). It is not a per-frame cost and not a throughput ceiling: over
a minute-long capture it would be under 1 % in any of them. Instrumented runs on the
Renesas configuration confirmed the writer one to two frames behind the camera for the
whole capture, and a 27 s run at 1024 rows closed the gap to 5 %.

Two earlier readings of the VM write data were wrong and are recorded here so they are
not repeated. (1) The ASMedia session's flat 256 MB/s end-to-end rate was read as a
storage ceiling; it is the per-capture overhead above. (2) A first Renesas sweep on
2026-08-25 ran the camera continuously in write mode and stopped it only after
`Capture = Done`; frames arriving during the file close overflowed the 21-deep plugin
queue and were reported as `DroppedArrays` (4–110 per point at 2048–256 rows). None
of them belonged in a file, but the number is indistinguishable from real loss after
the fact, so the script was changed to acquire exactly `NumCapture` frames
(`ImageMode = Multiple`) and the sweep re-run on 2026-08-26 — the Renesas document
holds only that clean run. The physical-host sweep used the continuous method too and
reported 0 drops; its NVMe closed files fast enough that the queue never overflowed.

**Data content.** The Renesas files were checked pixel by pixel after the sweep and
hold a camera-generated test ramp, not sensor data (see the Renesas document, "Data
content"). The ASMedia files were deleted before anyone looked, and the physical-host
run recorded real dark frames (mean ~68 ADU) in its characterisation notes. Frame
sizes, rates and loss counts are unaffected — the ramp travels the same path an image
would — but nothing measured on the VM says anything about the sensor.

## Stops and the deadlock

Each point ends with `Acquire = 0`. On the ASMedia configuration that stop froze the
IOC — the camera stopped completing USB transfers and whichever SDK call was in flight
under the asyn port lock hung forever ([../stop-deadlock.md](../incidents/stop-deadlock.md)).

| Configuration | Stops | Froze | At heights |
|---|---|---|---|
| Physical host, 2026-07-29 | 18 | 0 | — |
| VM, ASMedia, 2026-08-25 (incl. one upstream ADTucsen IOC and one with the temperature poll disabled) | 31 | **6** | 128, 32, 32, 8, 32, 32 — 6 of the 11 stops at ≤ 128 rows; 0 of 20 at ≥ 256 |
| VM, Renesas, 2026-08-25 + 26 | 56 | 0 | — (includes 10 deliberate stops at 32 rows and 10 at 8 rows) |

The kernel saw the difference too: the ASMedia logged
`xhci_hcd 0000:01:00.0: ERROR Transfer event TRB DMA ptr not part of current TD` on the
frame-data endpoint at every fast stop, deadlocking or not; the Renesas logged nothing
in 56 stops. Recovery from an ASMedia freeze was always a VM reboot (6 of 6); the
detector was never power-cycled. The freeze reproduced on the upstream ADTucsen driver
with the ASMedia (1 of 1), so it is not this driver's code — though the driver's
habit of making SDK calls under the port lock is what turned a dead USB endpoint into a
dead IOC, and hardening that remains on the list ([../TODO.md](../known-gaps/TODO.md) §1).

## Bottom line

- **Where the detector should live:** any configuration whose USB controller is not
  the ASMedia ASM2142. On the Renesas passthrough the VM is indistinguishable from bare
  metal for acquisition and loses nothing when writing.
- **Planning figures for the VM (Renesas):** frame rate ≈ 35 000 / height for heights
  of 64 rows and up (28 500 / height at 8 rows); the HDF5 writer keeps pace at every
  height; ~0.5 s overhead per capture.
- **The ASMedia numbers are history**, kept as the "before" and as the record of what
  the deadlock looked like.
