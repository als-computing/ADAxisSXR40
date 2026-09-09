# What differs from ADTucsen

ADAxisSXR40 started from upstream
[ADTucsen](https://github.com/djvine/ADTucsen) and diverged only where this
camera forced it to. This file records every deliberate divergence; each change
is justified by a measured property of this camera, recorded in the
characterisation notes, [../dhyana-xfxv4040bsi.md](../camera/dhyana-xfxv4040bsi.md).
The reasoning for why porting from ADTucsen was safe in the first place — same
SDK lineage, symbol-for-symbol API check, zero renumbered enum constants — is
in [../../RELEASE.md](../../RELEASE.md).

> **Two numbering schemes — mind the gap.** This file numbers *divergences from
> ADTucsen*; `RELEASE.md` numbers *changes in release order*. They agree on 1, 2
> and 5–8 and diverge everywhere else:
>
> | here | `RELEASE.md` | subject |
> |---|---|---|
> | 1, 2 | 1, 2 | timeout, row copy |
> | — | 3 | unsupported parameters kept, not pruned |
> | 3, 4 | 4 | TEC enable; ring telemetry |
> | 5–8 | 5–8 | pText, ROI clamp, ROI alignment, libjpeg |
> | — | 9–14 | template names, records, handle init, manuals, pool cap, padded copy |
> | 15, 16 | — | fixes taken from the PSI fork (below) |
>
> Quoting a bare number is ambiguous. Say "divergence 7" or "RELEASE change 9".

**1. `WaitForFrame` gets an explicit timeout.** Upstream used the header default
of `TUCAM_TIMEOUT` (1000 ms). This camera's exposure range reaches **3600 s**, so
relying on an undocumented default across a 3600× range is not defensible. Now
`exposure + 3000 ms`. `Buf_AbortWait` still breaks the wait immediately, so a
long timeout does not make the IOC unresponsive.

**The original justification for this change was wrong, and is corrected here.**
It previously claimed that any exposure past ~1 s returned `TUCAMRET_FAILURE` and
presented as a dead camera. That does not reproduce. Measured 2026-08-24 against
this camera on SDK 2.0.7.0, running **unmodified upstream ADTucsen** — which calls
the two-argument form and therefore takes the 1000 ms default:

| Exposure | Frames | Interval | Errors |
|---|---|---|---|
| 2 s  | 12 in 20 s | 2.000 s  | none |
| 10 s | 3 in 35 s  | 10.000 s | none |

Frame intervals matched the exposure exactly and nothing was logged. So
`nTimeOut` does not act as a deadline on the frame wait in this SDK — plausibly it
bounds individual USB transfers rather than the whole exposure, but that is a
guess and has not been confirmed.

The cause of the failure originally observed is therefore **unknown**. It is not
enough to substitute a new theory: change 11 (uninitialised handles, so
`uiRsdSize` reached `Buf_Alloc` as indeterminate memory) is a tempting
explanation, but upstream carries that same defect — it has no `memset` anywhere —
and upstream is what produced the clean table above. Neither candidate cause
reproduces. Treat this change as defensive hardening against an undocumented
default, not as a fix for a diagnosed fault, until someone reproduces the original
symptom and records the conditions.

**2. Frame data is copied row by row using `uiWidthStep`.** Upstream did one flat
`memcpy`, correct only while the buffer is unpadded.

**Superseded by change 14 in [../../RELEASE.md](../../RELEASE.md) — read that
first.** The paragraph below describes the state *before* 14 and is kept for the
reasoning only. When this was written the branch was genuinely unreachable,
because the size check and the row copy contradicted each other. Change 14
resolved that: the check now also accepts `nRows * uiWidthStep`, and only that, so
the row copy engages exactly when the SDK's own reported size confirms the stride
model and fails closed otherwise. The path remains **unexecuted on this camera**
(no padding mode has ever been observed) but is no longer dead by construction.

The original text: the size check earlier in `grabImage` compares the unpadded
`nCols*nRows*pixelSize`
against the SDK's `uiImgSize` and aborts on mismatch — so a padded buffer fails
there before reaching the copy. Measured 2026-07-29: every geometry tested passed
that check (full frame, 2×2 and 4×4 binned, ROIs down to 1000×600 with row byte
counts of 2000 and 1200), so `uiImgSize == width × height × 2` throughout and the
contiguous fast path is what always runs. The row loop is insurance against a
padding mode this camera does not appear to have; making it meaningful would
require the size check to accept padded buffers first. See the comment at the copy
site and [../TODO.md](../known-gaps/TODO.md).

**3. Added `AXIS_TEC_ENABLE`** (`TUIDC_ENABLETEC`) — absent upstream. Never
exercised, and two caveats documented at the call site.

**The cooler is already running, and this capability is decoupled from it.** It
reads `0` while the sensor sits well below ambient — −9.5 °C measured 2026-07-29,
−3.1 °C re-confirmed 2026-08-24, both with `ENABLETEC = 0`. The Peltier runs from
camera power-on regardless of this parameter.

That reframes the hazard rather than removing it. The AXIS manual's warning — a
water failure means "the sensor would overheat and possibly get damaged" — is a
**standing condition of having the camera powered**, not a consequence of writing
this record. Water must flow whenever the camera is on. Nothing in software can
see the loop, and withholding the control would not reduce the risk, because the
control is not what starts the cooler. Of the two directions, writing 1 cannot
start a cooler that is already running, and writing 0 would at worst warm the
sensor — an operational problem, not a damage mechanism.

The second caveat stands: the vendor capability table marks `ENABLETEC`
**unsupported** on 4040/4040BSI even though the runtime audit finds it present,
and an unsupported *Set* in this SDK fails silently — so it may well be a no-op.
`TECEnable_RBV` is kept precisely because its disagreement with the measured
temperature is the evidence for all of the above.

**4. Added `AXIS_BUFF_FRAMES` / `AXIS_BUFF_TOTAL`** (`TUIDI_CURRENTBUFFRAMES` /
`TUIDI_TOTALBUFFRAMES`) — ring telemetry. The SDK ring is only **2 frames** deep,
about 230 ms of slack at 33.5 MB/frame and 8.6 fps.

**Measured caveat:** at full frame the ring sits *permanently* full, so occupancy
is not the early warning it was intended to be — a signal saturated from the first
frame cannot warn about anything. `DroppedArrays_RBV` and achieved-vs-expected
frame rate are the real indicators. The depth cannot be raised either:
`TUCAM_FRAME.uiRsdSize` is documented as "how many frames do you want", but setting
it before `Buf_Alloc` left the SDK still reporting 2 frames and then crashed the
IOC with heap corruption — see [../../RELEASE.md](../../RELEASE.md) change 11. The two parameters
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
— easy to conflate. **Full per-id table, the three distinct failure modes, and how
to reproduce the audit: [../capabilities.md](../camera/capabilities.md).**

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
symbols (138 `jpeg_*`, 171 `TIFF*`, 399 `png_*`, 36 inflate/deflate), and
`libaxisSXR40.so` is the IOC's first `DT_NEEDED`, so libTUCam interposed on
ADSupport's copies. `NDFileJPEGConfigure` in `commonPlugins.cmd` segfaulted
inside TUCam's `jpeg_CreateCompress` before `iocInit` was ever reached. The fix
is in
[iocs/axisSXR40IOC/axisSXR40App/src/Makefile](../../iocs/axisSXR40IOC/axisSXR40App/src/Makefile),
which explains the mechanism in full. This is a consequence of linking TUCam into
an areaDetector IOC at all, so it will apply to any module that does.

---

## Fixes taken from the PSI fork

This module was ported from [djvine/ADTucsen](https://github.com/djvine/ADTucsen).
There is a second, more actively maintained fork,
[xiaoqiangwang/ADTucsen](https://github.com/xiaoqiangwang/ADTucsen) (PSI), whose
master carries commits through December 2025 that the djvine base does not. The
two below were found missing here by diffing against that fork and have been
applied. **When checking for upstream drift, diff against xiaoqiangwang, not
djvine.**

Its third recent commit, `6ee3e34` ("initialize ValueInfo.pText/nTextSize only
for string type"), needs no action — divergence 5 above fixes the same defect,
and does so more strictly, by also guarding the returned pointer against `NULL`.
`be090d6` (gain control) is already present.

**15. Trigger-output edge polarity was inverted** (upstream `c23ac88`). All six
`TriggerOut[123]Edge` / `_RBV` records labelled value 0 `FallingEdge`. The SDK
uses **opposite encodings for input and output triggers** — from `TUDefine.h`:

```c
TUCTD_FAILING = 0x00, TUCTD_RISING  = 0x01   // input  (TriggerEdge)
TUOPT_RISING  = 0x00, TUOPT_FAILING = 0x01   // output (TriggerOutNEdge)
```

`setTriggerOut()` assigns `nEdgeMode` straight from the parameter with no
translation, so selecting `RisingEdge` programmed a falling edge and vice versa
— silent, and wrong in hardware. The output records now read value 0 as
`RisingEdge`. **The input `TriggerEdge` records are correct as they stand and
were deliberately left alone**; they are the reason the mistake is so easy to
make, since the output records inherited their labels by copy-paste.

**16. A user-initiated stop logged a spurious error** (upstream `c0d7081`).
`stopCapture` breaks the frame wait with `TUCAM_Buf_AbortWait()`, which returns
`TUCAMRET_ABORT` from `TUCAM_Buf_WaitForFrame`. That was logged at
`ASYN_TRACE_ERROR` like any other failure, so every normal stop produced an
error line — and because divergence 1 added the timeout to the message text, it
read specifically as a timeout that had not elapsed. The log is now suppressed
for `TUCAMRET_ABORT`; the `asynError` return is unchanged.
