# What differs from ADTucsen

ADAxisSXR40 started from upstream
[ADTucsen](https://github.com/djvine/ADTucsen) and diverged only where this
camera forced it to. This file records every deliberate divergence; each change
is justified by a measured property of this camera, recorded in the
characterisation notes, [../dhyana-xfxv4040bsi.md](../dhyana-xfxv4040bsi.md).
The reasoning for why porting from ADTucsen was safe in the first place — same
SDK lineage, symbol-for-symbol API check, zero renumbered enum constants — is
in [../../RELEASE.md](../../RELEASE.md).

**1. `WaitForFrame` gets an explicit timeout.** Upstream used the header default
of 1000 ms. This camera's exposure range reaches **3600 s**, so any exposure past
~1 s returned `TUCAMRET_FAILURE` and presented as a dead camera — a routine
operating point for a soft X-ray detector, not an edge case. Now
`exposure + 3000 ms`. `Buf_AbortWait` still breaks the wait immediately, so a
long timeout does not make the IOC unresponsive.

**2. Frame data is copied row by row using `uiWidthStep`.** Upstream did one flat
`memcpy`, correct only while the buffer is unpadded.

**This branch is currently unreachable, and no padding has ever been observed.**
The size check earlier in `grabImage` compares the unpadded `nCols*nRows*pixelSize`
against the SDK's `uiImgSize` and aborts on mismatch — so a padded buffer fails
there before reaching the copy. Measured 2026-07-29: every geometry tested passed
that check (full frame, 2×2 and 4×4 binned, ROIs down to 1000×600 with row byte
counts of 2000 and 1200), so `uiImgSize == width × height × 2` throughout and the
contiguous fast path is what always runs. The row loop is insurance against a
padding mode this camera does not appear to have; making it meaningful would
require the size check to accept padded buffers first. See the comment at the copy
site and [../TODO.md](../TODO.md).

**3. Added `AXIS_TEC_ENABLE`** (`TUIDC_ENABLETEC`) — absent upstream. Two caveats
found later and documented at the call site: the TEC's hot side is **water
cooled**, and the AXIS manual states a water failure means "the sensor would
overheat and possibly get damaged", so this must not be enabled without
confirming flow; and the vendor capability table marks `ENABLETEC` **unsupported**
on 4040/4040BSI even though the runtime audit finds it present, so it may be a
no-op. Never exercised.

**4. Added `AXIS_BUFF_FRAMES` / `AXIS_BUFF_TOTAL`** (`TUIDI_CURRENTBUFFRAMES` /
`TUIDI_TOTALBUFFRAMES`) — ring telemetry. The SDK ring is only **2 frames** deep,
about 230 ms of slack at 33.5 MB/frame and 8.6 fps.

**Measured caveat:** at full frame the ring sits *permanently* full, so occupancy
is not the early warning it was intended to be — a signal saturated from the first
frame cannot warn about anything. `DroppedArrays_RBV` and achieved-vs-expected
frame rate are the real indicators. The depth cannot be raised either:
`TUCAM_FRAME.uiRsdSize` is documented as "how many frames do you want", but setting
it before `Buf_Alloc` left the SDK still reporting 2 frames and then crashed the
IOC with heap corruption. See [../TODO.md](../TODO.md) §1. The two parameters
remain useful for confirming the ring depth and for smaller geometries, where
occupancy does vary (at 1000×600 it stays at 0 while sustaining ~80 fps).

**Plus a startup capability audit.** `reportCapabilitySupport()` probes every id
the driver drives and logs which the camera actually implements, with a one-line
summary at every IOC start. There is no "list what you support" call in the SDK —
`*_GetAttr` failing is the only way to discover an unavailable id, and an
unsupported *Set* fails **silently**. Of the 26 ids inherited from ADTucsen, **8
are unimplemented on this model**: auto-exposure, CMS/HDR image mode, defect
correction, enhance, black level, brightness, sharpness, HDR-K. Note
`FLTCORRECTION` (flat field) *is* supported while `DFTCORRECTION` (defect) is not
— easy to conflate.

**5. Fixed the text-info calling convention.** `TUCAM_VALUE_INFO.pText` must be
**`NULL`** — the SDK returns a pointer to its own string rather than filling a
caller buffer. Upstream passed a local buffer, which returns `SUCCESS` with the
buffer untouched, which is why `ADModel`, `ADSDKVersion` and `ADFirmwareVersion`
were all blank. Fixed in both `getCamInfo` and `setCamInfo`; the camera now
reports model `Dhyana XF/XV4040BSI`, SDK `2.0.7.0`, firmware
`2c022311292c01220509`. Note `TUCAM_VALUE_TEXT` (used by `GetValueText`) has the
**opposite** convention and does want your buffer — see the table in
`sdk/sdk-overview.md` in the companion `AXIS-SXR-40-SDK` repository.

**6. Fixed a copy-paste bug in the ROI height clamp.** Upstream wrote the clamped
*height* into `ADSizeX`, corrupting the width parameter whenever the height needed
clamping.

**7. ROI values are aligned down — width to 8, height and both offsets to 4.**
The camera silently rounds anything unaligned, so an unaligned request came back
changed from `Cap_GetROI` and the EPICS readback disagreed with what was asked
for. The aligned values are written back to the parameters so EPICS reports what
was actually applied.

The requirement is **asymmetric, and the vendor GUI gets it wrong.** Measured
2026-07-29: widths that are multiples of 4 but not 8 come back changed —
1004 → 1000, 1012 → 1008, 996 → 992 — while 1000 and 1008 survive. Height keeps
every multiple of 4 (1004, 1012, 996 all survive), and so do both offsets (4, 12,
20). The vendor GUI masks everything with `((v >> 2) << 2)`
(`examples/cpp/QtDemo/camroi.cpp:112` in the companion SDK repository), which is
the only statement of the rule anywhere and is too permissive for width: it
leaves the camera silently narrowing half of all valid-looking width requests.

**IOC geometry.**
[st.cmd](../../iocs/axisSXR40IOC/iocBoot/iocAxisSXR40/st.cmd) is set
to 4096 × 4096 and `NELEMENTS=16777216`; upstream's 5,600,000 was sized for a
2048² camera and would have silently truncated our images. There is one startup
file, not a per-platform pair — the module builds `linux-x86_64` only, and the
second copy was how this geometry drifted out of step once already.

**8. The real libjpeg/libtiff/libpng are linked into the IOC binary.**
`libTUCam.so.1` statically bundles those libraries and exports every one of their
symbols (160 `jpeg_*`, 171 tiff, 399 `png_`, 37 deflate/inflate), and
`libaxisSXR40.so` is the IOC's first `DT_NEEDED`, so libTUCam interposed on
ADSupport's copies. `NDFileJPEGConfigure` in `commonPlugins.cmd` segfaulted
inside TUCam's `jpeg_CreateCompress` before `iocInit` was ever reached. The fix
is in
[iocs/axisSXR40IOC/axisSXR40App/src/Makefile](../../iocs/axisSXR40IOC/axisSXR40App/src/Makefile),
which explains the mechanism in full. This is a consequence of linking TUCam into
an areaDetector IOC at all, so it will apply to any module that does.
