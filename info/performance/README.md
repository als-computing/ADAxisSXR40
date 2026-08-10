# How to re-run the performance test

The AXIS test report §3.1 (`info/manuals/AXIS-SXR-40_USB3_702_Test_Report_Rev1/`)
tabulates frame rate against ROI height. This directory holds the method for
checking those figures through the EPICS IOC, and for measuring what file writing
costs on top.

Results live beside this file, one dated document per run —
[2026-07-29-roi-frame-rate.md](2026-07-29-roi-frame-rate.md) is the first.

## Quick version

```bash
# 1. start the IOC
cd iocs/axisSXR40IOC/iocBoot/iocAxisSXR40
./start_epics.sh          # or: ../../bin/linux-x86_64/axisSXR40App st.cmd

# 2. wait for it, then one point at a time
export PATH=/opt/epics/epics-base/bin/linux-x86_64:$PATH
./roi-rate-test.sh 4096 90          # acquire + HDF5 write
./roi-rate-test.sh 4096 90 nowrite  # acquire only
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

## Five things that will waste your afternoon

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
report a clean capture:

```bash
# sizes must equal frames x width x height x 2, plus a little HDF5 metadata
ls -l <outdir>/perf*.h5
```

For shape, read it back with an HDF5 build that is *not* the IOC's — that also
catches a stream written by a mismatched zlib. ADSupport ships one:

```c
/* h5dims.c */
#include <hdf5.h>
#include <stdio.h>
int main(int argc, char **argv){
    hid_t f = H5Fopen(argv[1], H5F_ACC_RDONLY, H5P_DEFAULT);
    hid_t d = H5Dopen2(f, "/entry/data/data", H5P_DEFAULT);
    hid_t s = H5Dget_space(d);
    hsize_t dm[3] = {0,0,0};
    int n = H5Sget_simple_extent_dims(s, dm, NULL);
    printf("rank=%d dims=[", n);
    for (int i = 0; i < n; i++) printf("%llu%s", (unsigned long long)dm[i], i<n-1?" x ":"");
    printf("]\n");
    return 0;
}
```

```bash
S=/opt/epics/synApps/support/areaDetector-R3-14/ADSupport
gcc -O1 -o h5dims h5dims.c -I$S/include -I$S/include/os/Linux \
    -L$S/lib/linux-x86_64 -lhdf5 -lzlib -lsz -Wl,-rpath,$S/lib/linux-x86_64
./h5dims <outdir>/perf4096_000.h5      # expect [frames x height x 4096]
```

## Status of this script

The measurement logic is the code that produced the
[2026-07-29 results](2026-07-29-roi-frame-rate.md). What has **not** been re-run
end to end is this packaged version, because the detector was powered down for
beamline maintenance shortly afterwards. Its pre-flight, geometry and CA handling
are verified; the acquire and write paths are unchanged from the run that produced
the numbers but deserve one confirming pass when the camera is back.

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
