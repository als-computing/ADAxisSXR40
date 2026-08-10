# Open problems — AXIS-SXR-40 / ADAxisSXR40

Last updated 2026-07-29. The IOC works against the camera: full-frame, binned and
ROI acquisition, TIFF and HDF5 (including zlib) writing, and software triggering are
all verified. **6 open items**, ordered by how much they block real use, then
host notes.

Two need equipment rather than a keyboard (1, 3); one needs a converter that is not
installed (4). The rest is small.

This file lists only what is still open. Work already done is not repeated here —
it lives where it is useful: the measured results and change history in the driver's
`RELEASE.md`, the reasoning behind each non-obvious decision in comments at the
relevant call site in `axisSXR40App/src/axisSXR40.cpp`, and the operating caveats in
its `README.md`. The driver is at
`/opt/epics/synApps/support/areaDetector-R3-14/ADAxisSXR40`.

The vendor manuals are converted to Markdown -- the two AXIS ones in
[manuals/](manuals/) here, the two Tucsen SDK ones in the companion
`AXIS-SXR-40-SDK` repository under `info/manuals/` -- and they answered
several questions that used to be on this list — check there before assuming
something is undocumented.

---

## 1. TEC enable has never been actuated — and now there are two reasons
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

## 2. `ReverseY` does not take, and nothing explains why

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

## 3. Hardware triggering still needs a signal source and a scope
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

## 4. The `.ui` screens are stale, and no converter is installed
The `medm` `.adl` screens are updated but
`axisSXR40App/op/ui/autoconvert/*.ui` still date from before and therefore still
show all 8 unsupported controls and none of the 3 new ones.

They live in a directory called `autoconvert`, so they are generated, not
hand-maintained — editing them by hand would be wrong and would drift. They need
regenerating from the `.adl` files with `adl2ui` (or caQtDM's converter), and
**neither is installed on this host**. Anyone using caQtDM rather than medm is
looking at the old layout until that happens.

## 5. The libTUCam interposition fix has a wider blast radius
Fixed and now proven for this IOC, but the underlying situation is not specific to
us and is worth writing down before it bites someone else.

`libTUCam.so.1` statically bundles libjpeg, libtiff, libpng and zlib and exports
**all** of their symbols — 160 `jpeg_*`, 171 tiff, 399 `png_`, 37
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

## 6. Small, mechanical

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
