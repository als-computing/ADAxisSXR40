# Open problems — AXIS-SXR-40 / ADAxisSXR40

Last updated 2026-08-26. The IOC works against the camera: full-frame, binned and
ROI acquisition, TIFF and HDF5 (including zlib) writing, and software triggering are
all verified. **8 open items**, ordered by how much they block real use, then
host notes — except the newest, §8, which is listed last but blocks everything: on
2026-08-26 the camera was found to be delivering a test ramp instead of images.

Two need equipment rather than a keyboard (2, 4); one needs a detector power cycle and a look at pixels (8); one needs a converter that is not
installed (5). One is a driver bug that blocks the others being exercised safely (1). The rest is small.

This file lists only what is still open. Work already done is not repeated here —
it lives where it is useful: the measured results and change history in the driver's
`RELEASE.md`, the reasoning behind each non-obvious decision in comments at the
relevant call site in `axisSXR40App/src/axisSXR40.cpp`, and the operating caveats in
its `README.md`. The driver is at
`/opt/epics/synApps/support/areaDetector-R3-14/ADAxisSXR40`.

The vendor manuals are converted to Markdown -- the two AXIS ones in
[manuals/](../manuals/) here, the two Tucsen SDK ones in the companion
`AXIS-SXR-40-SDK` repository under `info/manuals/` -- and they answered
several questions that used to be on this list — check there before assuming
something is undocumented.

---

## 1. `Acquire=0` can deadlock the IOC — `TUCAM_Cap_Stop` hangs while holding the asyn port lock *(operationally resolved 2026-08-25 by changing USB controller; driver hardening still open)*
Added 2026-08-25. Seen after continuous acquisition at 32 rows (2 of 2), 8 rows
(1 of 2) and 128 rows (1 of 3); not seen in 20 stops at ≥ 256 rows. After a high-rate
stop the camera stops completing USB transfers, and whichever SDK call is then in
flight under the asyn port lock blocks forever — caught twice with gdb: `TUCAM_Cap_Stop`
in `stopCapture()` (from `writeInt32`), and `TUCAM_Prop_GetValue` in the temperature
task, which polls under the lock every 0.5 s and so is the thread most likely to be
caught — turning a silent camera into a dead IOC within 0.5 s even when `Cap_Stop`
returns. Tested 2026-08-25 with `AXIS_NO_TEMP_POLL=1` (poll thread not started): the camera
still went silent after the first 32-row stop, and the next SDK call under the lock —
the exposure write, `TUCAM_Prop_SetValue` from `writeFloat64` — hung instead. The poll
is a victim, not a cause (n = 1); slowing or removing it is not a mitigation. A `usbmon`
capture of one deadlock (14:42) shows: `Cap_Stop` sends the camera no stop command,
only cancels host URBs; each cancel takes ~100 ms to complete (1.5 s for 15); the next
control transfer to the camera is submitted and never returned. Evidence in
[stop-deadlock.md](../incidents/stop-deadlock.md) "Below the SDK". `dmesg` at the same instant: the xhci driver
logged `Transfer event TRB DMA ptr not part of current TD` on the bulk endpoint
(`comp_code 28`, Stopped–Short Packet) — controller/driver ring desync during the
cancellation, also present on a stop that did *not* deadlock. Controller-path problem
(ASM2142 under VFIO). **Update 16:31:** the detector was moved to a Renesas uPD720202 controller (still
passthrough, same VM): **38 of 38 stops clean** across every height including 8 rows at 3567 fps, and the
acquire-only frame rates match bare metal at every height. The ASMedia controller was the amplifier.
Driver hardening (no SDK call under the lock) is still warranted — the SDK stop is
still command-less and untimed — but the operational problem is resolved by hardware. The port thread never
returns; every later `caput` to the driver queues forever; `DetectorState` stays
`Acquire`; plugins get nothing; `exit` and `SIGTERM` hang; `SIGKILL` wedges the
camera and a VM reboot is needed. Caught with gdb — full analysis, stacks, tally
and the fix in [stop-deadlock.md](../incidents/stop-deadlock.md).

**Fix:** never hold the port lock across an SDK call — `Cap_Stop`/`Buf_Release` move
into the image task (already unlocked there), `tempTask` calls the SDK unlocked and
locks only to store results, and property/capability writes need the same or a
bounded worker. Add a liveness watchdog (write round-trip). Report to Tucsen.

**Until fixed:** do not acquire at ROI heights ≤ 128 unattended. **Confirmed on
upstream ADTucsen too** (2026-08-25: Damon's IOC deadlocked on its first stop at 32
rows, identical signature) — this is the SDK's stop path, not this driver, and the
fix applies to both. Note `DetectorState_RBV` can read `Idle` while deadlocked (upstream always; this
driver in the temperature-task shape), so that field is not a usable indicator; a
write round-trip is.

## 2. TEC enable has never been actuated — and now there are two reasons
`TECEnable` reads `Disable`. Writing it has **not** been tried, and the manuals
turned a precaution into a documented hazard plus a doubt about whether it even
works.

**Hazard — the TEC is water cooled.** AXIS-SXR-40 user manual, callout J (p6):
*"A water supply failure would prevent the Peltier cooler from maintaining required
temperature on the sensor. The sensor would overheat and possibly get damaged."*
Section 6.4 adds: *"It is the sole responsibility of the user to decide which
temperature to set in order to avoid permanent damage to the sensor."*

Requirements from the manual: ~60 W to remove from the airbox; water at 15–20 °C
and ~1 l/min reaches a −20 °C sensor; the TEC can pull ~50 °C below the water. A
second hazard at low temperature: *"any trace of grease, gas, or water will
condensate on the sensor"* if the chamber vacuum is imperfect.

Nothing in software can see the coolant loop, so the driver cannot interlock this.
The record and the call site both carry the warning now.

**Doubt — it may be a no-op.** `Dhyana_Series_Properties&Capabilities` marks
`ENABLETEC (0x3B)` as **not supported** for both 4040 and 4040BSI, even though
`reportCapabilitySupport()` finds it present. Passing the audit is not proof of
usability — see item 3.

To test, with water confirmed flowing and someone present:

```
caput AXIS:SXR40:cam1:TECEnable Enable
# watch cam1:TemperatureActual (now real °C) fall
caput AXIS:SXR40:cam1:TECEnable Disable
```

The documented setpoint default for this model is 30, i.e. **−20 °C** (range
[0,100], "Min Temperature −50"), matching the manual's "−20 °C suitable for
measurements".

## 3. `ReverseY` does not take, and nothing explains why

The other three "supported but rejecting" parameters turned out to be fine — see
the `setCapability` readback fix (see the driver's RELEASE.md). `ReverseY`
(`TUIDC_VERTICAL`, capability 5) is the real one:

- `Dhyana_Series_Properties&Capabilities` 3.1.6 gives it as `[0, 1]`, default 0,
  "0: Non-vertical mirror state, 1: Vertical mirror state" — supported on the whole
  Dhyana series, **no precondition documented**.
- `reportCapabilitySupport()` finds it present.
- Writing 1 returns `NO_RESOURCE` **and** the readback stays 0, so unlike
  ATLEVELS/HISTC/FLTCORRECTION the value genuinely does not take. Writing 0
  "succeeds" only because it is already 0.

`ReverseX` was never observed to fail, so it is specifically the vertical mirror.
Possibly unimplemented in this firmware. Worth noting the AXIS user manual (p12)
says the software display shows the camera's H axis vertically and V axis
horizontally, so anyone reaching for a flip should check whether they actually want
`ReverseX`.

Low priority: image orientation is trivially fixed downstream in a plugin or in
analysis, and no experiment is blocked by it.

## 4. Hardware triggering still needs a signal source and a scope
The software half is done and recorded in the driver's RELEASE.md: `Software`
trigger mode gates
correctly and trigger-out configures on all three ports. What remains needs
equipment in the room:

- **External trigger-in** — `Standard`, `Synchronous` and `Global` modes have never
  seen a pulse. Needs a pulse generator. This camera reports no
  `TUIDC_ENABLEOVERLAP` and no rolling-scan control, so any upstream ADTucsen
  behaviour that assumed overlap will differ here, and which of the three modes are
  actually usable is unknown.
- **Trigger-out pulses** — the *configuration* round-trips, but nobody has put a
  scope on the ports to confirm a pulse appears with the requested delay and width,
  or that `Exposure Start` / `Exposure Global` / `Readout End` fire where their
  names claim.

## 5. The `.ui` screens are stale, and no converter is installed
The `medm` `.adl` screens are updated but
`axisSXR40App/op/ui/autoconvert/*.ui` still date from before and therefore still
show all 8 unsupported controls and none of the 3 new ones.

They live in a directory called `autoconvert`, so they are generated, not
hand-maintained — editing them by hand would be wrong and would drift. They need
regenerating from the `.adl` files with `adl2ui` (or caQtDM's converter), and
**neither is installed on this host**. Anyone using caQtDM rather than medm is
looking at the old layout until that happens.

## 6. The libTUCam interposition fix has a wider blast radius
Fixed and now proven for this IOC, but the underlying situation is not specific to
us and is worth writing down before it bites someone else.

`libTUCam.so.1` statically bundles libjpeg, libtiff, libpng and zlib and exports
**all** of their symbols — 138 `jpeg_*`, 171 `TIFF*`, 399 `png_*`, 36
deflate/inflate. Any areaDetector IOC that links TUCam gets those symbols into
the global scope ahead of ADCore's real copies, because the driver library is an
earlier `DT_NEEDED` than `libNDPlugin`.

Fix: `iocs/axisSXR40IOC/axisSXR40App/src/Makefile` links the real
libjpeg/libtiff/libpng directly into the executable so they win resolution. The
Makefile comment explains the mechanism in full. libtiff is confirmed by a valid
4096×4096 16-bit TIFF, and zlib is confirmed by a deflate-compressed HDF5 that
reads back cleanly. **libpng is still untouched by any test** — no plugin in the
current chain writes PNG.

Left open:

- **zlib turned out to be fine, and is staying uncovered on purpose.** Verified by
  writing an HDF5 with `Compression=zlib, ZLevel=6` (32 MB → 23.7 MB) and reading
  it back with a *separate* clean HDF5 build: `filters=1 [deflate lvl=6]`,
  `H5Dread` succeeded, mean 1545.92 against 1544.64 uncompressed. So whichever
  `deflate` the IOC bound produces a standards-valid stream, and adding a second
  zlib to the link — which risks clashing with HDF5's own — is unnecessary.
- **An upstream ADCore bug is worth reporting.** `NDFileJPEG.cpp:310` calls
  `jpeg_create_compress()` one line *before* assigning `jpegInfo.err`. When
  libjpeg's entry consistency check fails it takes its `ERREXIT` path, which
  dereferences that still-uninitialised pointer — so a version mismatch
  segfaults instead of printing a diagnostic. Correct libjpeg keeps it latent,
  but the ordering is wrong regardless and cost real time to diagnose here.
- Any future ADTucsen/ADDhyana module will need the same treatment.

## 7. Small, mechanical

- **The ROI cannot be grown back to full frame without zeroing the offsets first.**
  Setting `SizeX`/`SizeY` while a non-zero `MinX`/`MinY` is still in place clamps the
  size against the old offset, and it never re-expands when the offset later goes to
  0. `SizeX=4096, SizeY=4096` then `MinX=0, MinY=0` left the detector at 3992 × 4032
  with no error and a readback that quietly said so. Offsets first, then sizes.
  Either document it on the OPI or have `setROI()` re-expand when an offset shrinks.
- **`getcwd` return value unchecked**, `axisSXR40.cpp:388`. Inherited from
  upstream, emits a compiler warning, harmless. Just tidy it.
- **`provenance.md` — confirm the `Library/` wrapper.** The layout table
  describes vendor paths as `Library/sdk/`, `Library/TUCamSample/`,
  `Library/bin/`, `Library/readme`, but the download extracted with those four at
  the top level and no `Library/` above them. Probably just how it was unpacked;
  worth one check against a fresh extraction so the table is right.

---

## 8. The camera is delivering a synthetic test ramp instead of sensor data *(found 2026-08-26)*

**What was seen.** Every frame written by the 2026-08-26 Renesas benchmark — 22 090
frames in nine files, plus single-frame probes taken afterwards at 50 ms, 1 s and 5 s
exposure — has min 0, max 65280, mean exactly 32640.0 and 1/256 of its pixels at zero:
256 distinct values, all multiples of 256, decreasing by 256 per column, shifting by
256 per row, with an arbitrary offset per frame. `FrameFormat = Usual` gives the same
ramp after the SDK's level processing (two values, 33338 and 32195, the latter exactly
where the raw ramp is zero). A real dark frame from this camera has mean ~68 ADU and
sensor noise ([dhyana-xfxv4040bsi.md](../camera/dhyana-xfxv4040bsi.md), measured 2026-07-29 on
the physical host).

**What it is not.** Not exposure (identical at 50 ms, 1 s, 5 s), not the frame format,
not the driver's copy path (a moving 8-bit ramp cannot be manufactured from sensor data
by a wrong offset or stride — and the size check passes), not the HDF5 writer (the
pattern is in the camera's own `Raw` frames). It is generated inside the camera: either
its test-image generator (`TUIDC_TESTIMGMODE`, which the SDK reports as *unsupported*
on this unit, so nothing in this software could have enabled it) or a substitute
pattern the FPGA emits when it receives nothing from the sensor.

**What is not known.** When it started. No run on this VM (2026-08-24 onward) inspected
pixel values before 2026-08-26; the upstream-ADTucsen frames on 2026-08-25 were counted,
not looked at. The detector was power-cycled on 2026-08-25 (morning) and the camera
moved between USB controllers that afternoon.

**To do, in order.**

1. Power-cycle the detector, start the IOC, take one 50 ms full frame into HDF5 and
   run `tools/h5check` on it. Mean near 68 with noise → the pattern was a
   transient state and this item closes with a note. Still 32640.0 → hardware/firmware
   fault; contact AXIS/Tucsen with the ramp description above.
2. If it persists, confirm with the vendor's own tool (Mosaic, Windows) on a laptop
   plugged directly into the camera, to take the whole EPICS/VM/passthrough stack out
   of the question.
3. Regardless: the benchmark script has no way to know whether it is timing images or
   a pattern. Add a content check to the write-mode leg (build `h5check` once, run it
   on the file, fail on `mean == 32640.0`), or at least make the README's manual check
   part of the procedure.
4. The frame-rate, loss and deadlock results are unaffected — the ramp has the frame's
   real size and travels the real path — but nothing measured on this VM says anything
   about the sensor. Both VM results documents and `comparison.md` carry the caveat.

## Host and environment (not code)

### `medm` is not installed on this host
`iocBoot/iocAxisSXR40/start_epics.sh` opens the main screen with
`medm -x -macro ... AxisSXR40.adl`, and `medm` is not on this machine — so the
script's GUI half silently fails and only the IOC comes up. Either install medm
(EPICS extensions) or switch the launcher to caQtDM once item 4 is resolved.

Noted here because the screens were just reworked and cannot be visually confirmed
against live PVs on this host. They were verified structurally instead: balanced
braces, 114 PV references with **zero** dangling, and a rendered layout preview.

### `usbfs_memory_mb` is 16 MB while one frame is 32 MiB

Raised by Xiaoqiang Wang (PSI) by email, 2026-07-28, in the context of running two
cameras on one Linux host.

On this host `/sys/module/usbcore/parameters/usbfs_memory_mb` is **16**, i.e. half
a frame. It is evidently not biting — TUCam must split its bulk transfers into
URBs below the limit, since continuous acquisition sustained ~9 fps with zero
dropped frames. Recorded because it is a plausible suspect the moment anything
USB-throughput-related misbehaves, and because Wang's specific warning was about
**two cameras on one host**, which we have not tried.

One-line, reversible, non-persistent:

```
echo 1000 | sudo tee /sys/module/usbcore/parameters/usbfs_memory_mb
```

Caveat on the rest of that email: Wang's link is to **ids-imaging.com**, so his
Axis units contain **IDS** cameras, not Tucsen — his EPICS driver is almost
certainly ADAravis/ADGenICam against IDS, which is precisely the path that does
not work for ours. Do not assume his driver experience transfers.
