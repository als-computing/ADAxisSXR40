# How to re-run the performance test

> The script now lives in [`tests/performance/roi-rate-test.sh`](../../tests/performance/roi-rate-test.sh)
> (moved 2026-09-11; a pytest wrapper there checks each height against the numbers recorded
> here). This folder keeps the method and the dated results.

The AXIS test report §3.1 (`info/manuals/AXIS-SXR-40_USB3_702_Test_Report_Rev1/`)
tabulates frame rate against ROI height. This directory holds the method for
checking those figures through the EPICS IOC, and for measuring what file writing
costs on top.

Results live beside this file, one dated document per configuration, each holding
only that configuration's own numbers:
[2026-07-29-roi-frame-rate-physical.md](2026-07-29-roi-frame-rate-physical.md) (bare-metal
host), [2026-08-25-roi-frame-rate-vm-asmedia-bl1101ad01.md](2026-08-25-roi-frame-rate-vm-asmedia-bl1101ad01.md)
(KVM guest `bl1101ad01`, detector on an ASMedia ASM2142 passthrough controller — the
configuration that deadlocked) and
[2026-08-26-roi-frame-rate-vm-renesas-bl1101ad01.md](2026-08-26-roi-frame-rate-vm-renesas-bl1101ad01.md)
(same guest, Renesas uPD720202 controller — clean, bare-metal speed). The three are
put side by side in [comparison.md](comparison.md); keep comparisons there, not in the
per-configuration files. Name new ones `<date>-roi-frame-rate-<host-or-config>.md`.

Sustained-load results come from the test suite's stress tier: `tests/run.sh stress all
--record` writes `<date>-stress-<driver>-<host>.md` here (Conditions table naming the driver and IOC,
one row per HDF5 streaming run with camera/writer rates, drops, queue and pool peaks, RSS,
file check, plus the long-run, capture-cycle, viewer and provoke summaries). Method and
assertions: [tests/stress/README.md](../../tests/stress/README.md). The first such file is
[2026-09-11-stress-adaxissxr40-bl1101ad01.md](2026-09-11-stress-adaxissxr40-bl1101ad01.md).

## Quick version

```bash
# 1. start the IOC
cd iocs/axisSXR40IOC/iocBoot/iocAxisSXR40
./start_epics.sh          # or: ../../bin/linux-x86_64/axisSXR40App st.cmd

# 2. wait for it, then one point at a time
export PATH=/opt/epics/epics-base/bin/linux-x86_64:$PATH
../../tests/performance/roi-rate-test.sh 4096 90          # acquire + HDF5 write
../../tests/performance/roi-rate-test.sh 4096 90 nowrite  # acquire only
```

The whole sweep, both modes, is nine heights: 4096 2048 1024 512 256 128 64 32 8.
Frame counts used last time are in the results document; they are chosen so each
run lasts roughly 5–10 s.

## What is being measured, and against what

| | |
|---|---|
| **Acquire only** | `ArrayCallbacks` disabled, so no plugin sees a frame. Isolates camera + driver. |
| **Acquire + write** | Full `commonPlugins.cmd` chain active, `NDFileHDF5` streaming uncompressed to disk. |
| **Rate** | Counted from `ArrayCounter_RBV` (acquire-only) or `HDF1:NumCaptured_RBV` (write) over a wall clock. |
| **Loss** | `HDF1:DroppedArrays_RBV`, and `image1:DroppedArrays_RBV` for the display path. |

Rates are compared against the vendor's table, which holds **width at 4096** and
varies only height. That is not an arbitrary choice on their part: this is a rolling
shutter, frame rate goes as 1/height, and narrowing the width buys very little. Test
the same way or the numbers are not comparable.

## Eight things that will waste your afternoon

Every one of these cost real time the first time round.

**1. HDF5 Stream mode fixes the geometry when `Capture` starts.** It uses the
dimensions of the last array the plugin saw, *not* the current ROI. Change the ROI
and start `Capture` without acquiring a frame in between and every frame is rejected
with `"Invalid frame. Ignoring."` — `NumCaptured` stays 0, you get a ~100 byte file,
and **the detector reports no error at all**. Always acquire one frame at the new
geometry first. `roi-rate-test.sh` does this and verifies it worked.

**2. Set offsets before sizes.** Writing `SizeY` while a non-zero `MinY` is still in
place clamps the size against that offset, and it does not re-expand when the offset
later goes to zero. Asking for 4096 after a previous ROI can quietly leave you at
3992 × 4032.

**3. Short runs badly understate the rate.** 30 full frames measured 6.4 fps against
8.2 fps for 90, because file open and close are a fixed cost spread over fewer
frames. Use enough frames that the fixed cost disappears — at least ~5 s of running.

**4. Do not benchmark writing to `/tmp`.** On this host `/tmp` is **tmpfs**, i.e.
RAM, and will happily report 3.7 GB/s. That measures memory bandwidth, not storage.
Write to real storage — `/home` here is NVMe at 1.7 GB/s, roughly 6x the camera, so
it is not the bottleneck. Check first:

```bash
df -Th <outdir>                                   # must not say tmpfs
dd if=/dev/zero of=<outdir>/spd.bin bs=1M count=2048 oflag=direct
```

**5. Exposure must be shorter than the frame period, or it becomes the limit.**
At 3726 fps the period is 268 µs. The script sets 20.64 µs (2 × the 10.32 µs sensor
row time), safely below every point in the table. If you see a rate pinned near
`1/exposure`, this is why.

**6. Stopping after a fast point can deadlock the IOC — and the *next* point, not
this one, is where you will notice.** `Acquire=0` after acquiring at 32 or 8 rows — and
once at 128 — has left the camera not completing USB transfers, which hangs whichever
SDK call the driver has in flight under its asyn port lock (`TUCAM_Cap_Stop`, or the
0.5 s temperature poll). Nothing errors. The next invocation fails with `SizeY did not
take`, which sends you at the ROI logic, the camera, or its firmware — it is none of
those; the write never reached the driver. The script now proves the driver is
alive after every stop with a write that must round-trip (an `ArrayCounter` reset) —
`DetectorState_RBV` alone can read `Idle` while deadlocked — and exits 2 pointing at
[../stop-deadlock.md](../incidents/stop-deadlock.md) if it does not. Recovery is `SIGKILL`
plus a VM reboot (the kill wedges the camera; neither a USB device rebind nor an xhci
controller reset is enough — only a reboot has worked).
**Run the small heights last** so a deadlock costs nothing already measured.

**7. In continuous mode, `DroppedArrays` counts frames that arrive *after* the capture
is complete — and they look like data loss.** The camera keeps streaming for the
~0.5–1 s it takes the plugin to close a 1.7 GB file; those frames overflow the 21-deep
queue and are counted. Every file still holds its full `NumCapture`. Measured
2026-08-26 with time-stamped monitors: the first drop always came *after*
`NumCaptured == N`. Related: the wall-clock fps of a write point includes a fixed ~0.3–0.6 s of
camera start-up and file close (2026-08-26, Multiple mode), so a 6 s run understates
the writer by 6–9 % and a 27 s run by 5 %; it is overhead, not a per-frame cost. And neither `HDF1:IOSpeed` nor
`HDF1:ExecutionTime` measures the pipeline (one times `H5Dwrite` only, the other the
queueing callback), so do not diagnose with them. The script now acquires exactly N
frames in write mode (`ImageMode = Multiple`), which makes `DroppedArrays` mean what
it says, and reports a stalled capture instead of waiting 60 s for it.

**8. A perfect-looking file can hold no image at all.** Every counter, size and
timestamp in the 2026-08-26 sweep was exactly right, and every pixel was a
camera-generated test ramp (`mean=32640.0` on every frame). No PV shows this — the
driver, the plugins and the script all see a frame of the right size arriving at the
right rate. Look at pixel statistics of at least one frame per session with
[h5check.c](../../tools/h5check/h5check.c) (below) before trusting anything about *content*; rate and
loss figures are unaffected either way.

Two smaller ones: readbacks lag, so poll `SizeY_RBV`/`ArraySizeY_RBV` until they
match rather than sleeping and hoping; and the first acquire after IOC start
sometimes produces nothing, so the script retries the priming frame up to three
times.

**And one about Channel Access.** The detector IOC runs on the local machine, but a
beamline shell normally has `EPICS_CA_ADDR_LIST` pointed at a gateway — here
`cagw-bldmz.als.lbl.gov`, which serves accelerator PVs and is entirely legitimate.
Inherit it unchanged and every `caget` times out against a detector running on this
very machine, with no hint why. The script therefore *prepends* `127.0.0.1` rather
than replacing the list, so the local detector and the site's PVs both resolve. Its
pre-flight check reports the effective list when nothing answers.

## Verifying the files are real

`NumCaptured` and `DroppedArrays` say the plugin thinks it wrote everything. Check
the file actually holds the frames — a compressed or truncated file will still
report a clean capture — **and check that the frames hold an image.** On 2026-08-26
a complete, structurally perfect sweep turned out to contain a camera-generated test
ramp instead of sensor data, and nothing upstream of a pixel-level look could have
told anyone.

```bash
# sizes must equal frames x width x height x 2, plus a little HDF5 metadata
ls -l <outdir>/perf*.h5
```

[h5check.c](../../tools/h5check/h5check.c) reads a file back with an HDF5 build that is *not* the IOC's
(ADSupport ships one — which also catches a stream written by a mismatched zlib) and
prints, per file: shape, type and chunking; min/max/mean/zero-fraction of the first,
middle and last frame; whether `NDArrayUniqueId` runs 1 … N without gaps; and the frame
rate from the camera timestamps stored in the file — an independent check on the
script's wall-clock figure.

```bash
S=/usr/local/epics/support/areaDetector/ADSupport      # or your ADSupport
gcc -O2 -o h5check ../../tools/h5check/h5check.c -I$S/include/os/Linux \
    -L$S/lib/linux-x86_64 -lhdf5 -lzlib -lsz -Wl,-rpath,$S/lib/linux-x86_64
for f in <outdir>/perf*.h5; do ./h5check $f; done
```

What good looks like: dims `[frames x height x 4096]`, `uint16`, `UniqueId … missing=0`,
timestamp fps within a few percent of the acquire-only figure, and pixel statistics
that look like a **dark sensor**: mean of a few tens of ADU (~68 at 50 ms on this unit,
see [../dhyana-xfxv4040bsi.md](../camera/dhyana-xfxv4040bsi.md)), max in the hundreds to low
thousands (hot pixels), zero fraction essentially nil, and the numbers *different*
from frame to frame. What bad looks like: `min=0 max=65280 mean=32640.0 zeros=0.39%`
on every frame — a 256-level ramp in the high byte, the camera's test pattern.

## Status of this script

The measurement logic is the code that produced the
[2026-07-29 results](2026-07-29-roi-frame-rate-physical.md), and it has since been
re-run end to end on `bl1101ad01` (2026-08-25 and 2026-08-26, KVM guest — see the two
VM results documents beside this file). The acquire-only path reproduced cleanly at all nine
heights. The write path exposed one weakness in the script itself: the prime check
accepted a stale `ArraySizeY_RBV` and so could pass without a frame, which masked a
dead driver — it now requires `ArrayCounter_RBV` to advance. The same run found the
stop deadlock (thing 6 above); the script now fails fast on it. The timing and rate
calculations are unchanged from the run that produced the physical-host numbers, with
one deliberate method change on 2026-08-26: write mode acquires exactly N frames
(`ImageMode = Multiple`) rather than running continuously and stopping after
`Capture = Done`, so post-capture frames no longer inflate `DroppedArrays` (thing 7).

## Clean up

A full sweep writes on the order of 15 GB. The script does not delete anything —
remove the output directory yourself when done.

```bash
du -sh /home/$USER/axis-perf-tmp && rm -rf /home/$USER/axis-perf-tmp
```

## Where the numbers end up

Summary table in the module's [RELEASE.md](../../RELEASE.md) under *"Frame rate
versus ROI height — measured"*; full detail and conditions in the dated results
document here. If you re-run on different hardware, add a new dated file rather
than editing the old one — the host storage and USB controller are part of the
result.
