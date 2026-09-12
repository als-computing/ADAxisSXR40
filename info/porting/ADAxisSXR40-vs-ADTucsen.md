# ADAxisSXR40 vs ADTucsen — functional comparison

Compares the two areaDetector drivers for the Tucsen TUCam SDK that live side by side
on this host:

| | ADAxisSXR40 | ADTucsen |
|---|---|---|
| Path | `areaDetector/ADAxisSXR40` | `areaDetector/ADTucsen` |
| Owner on this host | gabrielgazolla | daenglis (Damon English) |
| Driver source | `axisSXR40App/src/axisSXR40.cpp` (2223 lines) | `tucsenApp/src/tucsen.cpp` (1515 lines) |
| Class / port config | `axisSXR40` / `axisSXR40Config()` | `tucsen` / `tucsenConfig()` |
| Param prefix | `AXIS_*` | `T_*` |
| Lineage | Fork of ADTucsen, with PSI fixes back-ported | PSI fork (xiaoqiangwang/ADTucsen), unmodified driver code |
| Driver version string | 0.2.0 | 0.2.0 |
| TUCam SDK | `/usr/local/lib/tucsen/libTUCam.so.1.0.0`, headers `/usr/local/include/tucsen` | vendored in `tucsenSupport/os/linux-x86_64/`, headers in `tucsenSupport/` |

Comparison date: 2026-09-09. Method: both `.cpp` files were name-normalised
(`AxisSXR40`→`Tucsen`, `AXIS_`→`T_`), comment-stripped and diffed; the same was done
for the `.template`, `_settings.req`, `.adl` and IOC files. Every claim below was
checked against the code, not taken from either module's own documentation.

---

## 1. Short answer

**Same core functionality, not the same behaviour.**

Both drivers expose the same acquisition model, the same 42 camera-specific parameters,
the same trigger-in and 3-port trigger-out handling, the same enum menus populated from
the SDK, and the same record names. An OPI built for one will drive the other (apart
from four records only ADAxisSXR40 has). Both link the byte-identical SDK library and
headers.

ADAxisSXR40 is ADTucsen plus:

- **3 extra parameters**: `TECEnable`, `BuffFrames_RBV`, `BuffTotal_RBV`.
- **1 removed menu entry**: `FrameFormat = RGB888` (mono sensor; selecting it stalls acquisition).
- **4 real bug fixes** not present in ADTucsen: ROI height clamp writing into `SizeX`,
  `AutoLevels` never publishing the histogram readback, SDK handles used uninitialised,
  `FrameFormat` index unchecked.
- **Behavioural changes** for this specific camera: explicit frame-wait timeout, ROI
  alignment (width 8 / height 4 / offsets 4), `TemperatureActual` converted to °C with a
  per-unit calibration, `setCapability` tolerating the SDK's `NO_RESOURCE` code when the
  readback matches, padded-buffer copy path, text-info calling convention changed.
- **Diagnostics**: startup capability audit, ring-occupancy telemetry, richer error
  messages, `AXIS_NO_TEMP_POLL` diagnostic switch.
- **IOC configuration** sized for the 4096×4096 camera (ADTucsen's example IOC is sized
  for a 2048² camera and would truncate images from the AXIS detector).

ADTucsen has nothing functional that ADAxisSXR40 lacks, except the `RGB888` frame
format for colour Dhyana models and vendored SDK files for Windows.

---

## 2. Provenance — which ADTucsen is this?

ADAxisSXR40's own porting notes (`differences-from-adtucsen.md`) say it was
ported from **djvine/ADTucsen** and that two fixes had to be pulled from the **PSI fork**
(xiaoqiangwang/ADTucsen). Damon's copy is *already* the PSI fork: it carries both of
those fixes.

| PSI fix | In Damon's ADTucsen | Evidence |
|---|---|---|
| `c0d7081` — `TUCAMRET tucStatus` type and no error log on `TUCAMRET_ABORT` | yes | `tucsen.cpp:559`, `tucsen.cpp:579` |
| `c23ac88` — trigger-out edge labels `0 = RisingEdge` | yes | `tucsen.template:656` |
| `6ee3e34` — init `pText`/`nTextSize` only for string types | yes | `tucsen.cpp:1058-1061` |
| `be090d6` — gain control | yes | `tucsen.cpp:932` |

So "divergences 15 and 16" in the AXIS porting notes are **not** differences relative to
this ADTucsen. They are differences relative to djvine's repo only.

Both IOCs also carry the same **libjpeg/libtiff link-order fix** in
`iocs/*/…App/src/Makefile` (libTUCam bundles its own libjpeg and would otherwise
interpose on ADSupport's, crashing `NDFileJPEG` before `iocInit`). Damon's copy has it
in `tucsenIOC/tucsenApp/src/Makefile` with `Makefile.orig` preserved alongside.

Both define `TUCAM_TARGETOS_IS_LINUX` (ADTucsen via `configure/CONFIG_SITE.local`,
ADAxisSXR40 in the src `Makefile`), without which `TUDefine.h` selects the macOS branch
and fails to compile.

---

## 3. SDK

Identical bits, different packaging.

| | ADAxisSXR40 | ADTucsen |
|---|---|---|
| `libTUCam.so.1.0.0` | `/usr/local/lib/tucsen/` (system install) | `tucsenSupport/os/linux-x86_64/`, copied to `lib/linux-x86_64/` at build |
| `TUCamApi.h` md5 | `c3b3f27c…` | `c3b3f27c…` |
| `TUDefine.h` md5 | `af2d16e6…` | `af2d16e6…` |
| Binary | `cmp` reports identical | same |
| `ldd` of IOC | `libTUCam.so.1 => /usr/local/lib/tucsen/…` | `libTUCam.so.1 => …/ADTucsen/lib/linux-x86_64/…` |
| Windows SDK | not included | `TUCam.dll`, `TUCam.lib` vendored |
| Header date | 2023-01-05 (SDK reports 2.0.7.0 at runtime) | same |

ADAxisSXR40's `CONFIG_SITE` says the headers live in `/usr/local/include/tucam` and the
library in `/usr/lib/x86_64-linux-gnu`; on this host `CONFIG_SITE.local` overrides that
to `/usr/local/include/tucsen` and `/usr/local/lib/tucsen`. ADTucsen has no external
SDK dependency and is self-contained.

Practical consequence: the two IOCs can coexist on the machine, but not against the
same camera at the same time (the SDK opens the device exclusively).

---

## 4. Parameter and record inventory

### Identical in both (42 camera parameters)

`Bus`, `ProductID`, `TransferRate`, `FrameSpeed`, `BitDepth`, `BinMode`, `FanGear`,
`GainMode` (image mode), `AutoExposure`, `FrameFormat`, `AutoLevels`, `Histogram`,
`Enhance`, `DefectCorrection`, `Denoise`, `FlatCorrection`, `DynRgeCorr`,
`Brightness`, `BlackLevel`, `Sharpness`, `NoiseLevel`, `HDRK`, `Gamma`, `Contrast`,
`LeftLevel`, `RightLevel`, `TriggerEdge`, `TriggerExposure`, `TriggerDelay`,
`TriggerSoftware`, `TriggerOut{1,2,3}{Mode,Edge,Delay,Width}`.

Plus the standard `ADBase` set: `Acquire`, `AcquireTime`, `Gain`, `Temperature`,
`TemperatureActual`, `MinX/Y`, `SizeX/Y`, `ReverseX/Y`, `TriggerMode`, `ImageMode`,
`NumImages`, etc.

Record names (`$(P)$(R)Name`) are the same in both templates. Only the asyn drvInfo
string differs (`AXIS_…` vs `T_…`), which is invisible to clients.

### Only in ADAxisSXR40

| Record | Type | SDK id | Purpose |
|---|---|---|---|
| `TECEnable` / `TECEnable_RBV` | mbbo / mbbi | `TUIDC_ENABLETEC` | Thermoelectric cooler enable. Never exercised; measured to be decoupled from actual cooler state (cooler runs from power-on regardless). Deliberately **excluded** from autosave (`axisSXR40_settings.req:40-50`). |
| `BuffFrames_RBV` | longin | `TUIDI_CURRENTBUFFRAMES` | Frames currently in the SDK ring (polled at 0.5 s). |
| `BuffTotal_RBV` | longin | `TUIDI_TOTALBUFFRAMES` | Ring capacity (reads 2 on this camera). |
| `TemperatureActual` | ai (override) | — | Adds `PREC=2`; value converted to °C by the driver (see §5). |

### Only in ADTucsen

| Item | Notes |
|---|---|
| `FrameFormat` choice `RGB888` (value 2) | Removed in ADAxisSXR40 (`frameFormats[]` has 2 entries, `axisSXR40.cpp:160`). On a mono sensor `WaitForFrame` returns `NOT_SUPPORT` and acquisition stalls until `Acquire` is cycled. Needed only for colour Dhyana models. |

### OPI screens (`op/adl`)

ADAxisSXR40 removed the widgets for the 8 controls the camera does not implement
(`AutoExposure`, `Brightness`, `BlackLevel`, `Sharpness`, `HDRK`, `Enhance`,
`DefectCorrection`, `GainMode`) and the `Bus` string, and added `TECEnable` and the two
ring counters. The records themselves are kept in both templates. ADAxisSXR40's
`op/ui/autoconvert/*.ui` files are stale (not regenerated); ADTucsen's `.ui` and `.adl`
match each other.

---

## 5. Driver code differences

Names normalised; line refs are to the actual files.

### 5.1 Acquisition path

| Aspect | ADTucsen | ADAxisSXR40 | Impact |
|---|---|---|---|
| `TUCAM_Buf_WaitForFrame` timeout | 2-arg form, header default 1000 ms (`tucsen.cpp:576`) | `exposure×1000 + 3000 ms` (`axisSXR40.cpp:851-858`) | AXIS notes admit the original justification ("exposures > 1 s failed") did **not** reproduce on unmodified ADTucsen at 2 s and 10 s. Treat as defensive hardening. |
| `frameHandle_.uiRsdSize` before `Buf_Alloc` | never set before first `Buf_Alloc`; set to 1 only inside `setTrigger()` (`tucsen.cpp:1325`) | set to 1 every start (`axisSXR40.cpp:730`) | In ADTucsen the first `Buf_Alloc` after boot reads an **uninitialised** field unless a trigger write happened first. |
| SDK handle initialisation | none; `frameHandle_`, `triggerHandle_`, `triggerOutHandle_[]`, `camHandle_` are indeterminate | `memset` to 0 in constructor (`axisSXR40.cpp:355-358`) | Same root cause as above. Latent bug in ADTucsen. |
| Frame size check | hard abort if `w×h×bytes ≠ uiImgSize` (`tucsen.cpp:653`) | also accepts `nRows × uiWidthStep` (padded) and only that (`axisSXR40.cpp:979-1002`) | No padding has ever been observed on this camera; both paths behave identically in practice. |
| Frame copy | single `memcpy` (`tucsen.cpp:674`) | contiguous fast path, else row-by-row via `uiWidthStep` (`axisSXR40.cpp:1060-1072`) | Same as above. |
| Frame geometry trace | none | `TRACE_FLOW` line with width/height/format/widthStep/offset per frame (`axisSXR40.cpp:892`) | Diagnostic only. |
| `NDArrayPool` exhaustion | generic "not enough buffers left" | reports bytes, pool used/max, buffer count; sets a specific `StatusMessage` that `imageGrabTask` preserves (`axisSXR40.cpp:1020-1030`, `:780-783`) | Diagnostic only. |
| Log on user stop (`TUCAMRET_ABORT`) | suppressed (`tucsen.cpp:579`) | suppressed (`axisSXR40.cpp:868`) | Same. |

### 5.2 Parameter writes

| Aspect | ADTucsen | ADAxisSXR40 | Impact |
|---|---|---|---|
| ROI height clamp | writes clamped height into **`ADSizeX`** (`tucsen.cpp:1412`) — copy-paste bug | writes into `ADSizeY` (`axisSXR40.cpp:2087`) | Real bug, but **masked**: `Cap_SetROI` still gets the correct local width and `ADSizeX` is overwritten from `Cap_GetROI`. No visible effect (tested on both drivers, 2026-09-11). |
| ROI alignment | none | `MinX &= ~3`, `SizeX &= ~7`, `MinY &= ~3`, `SizeY &= ~3` before `SetROI` (`axisSXR40.cpp:2114-2119`) | The camera rounds width (8) and `MinX` (4) itself, so those readbacks agree under both drivers. It does **not** round `SizeY`/`MinY`: ADTucsen passes 1006 / 14 through, ours aligns to 1004 / 12 (tested on both, 2026-09-11). |
| `TUCAM_ROI_ATTR` init | not zeroed | `memset` (`axisSXR40.cpp:2122`) | Hygiene. |
| `setCapability` on SDK error | returns `asynError` (`tucsen.cpp:1174`) | reads the value back; if it matches, returns success at `TRACE_FLOW` (`axisSXR40.cpp:1838-1847`) | On this camera `ATLEVELS`, `HISTC`, `FLTCORRECTION` return `NO_RESOURCE` but apply. ADTucsen logs a burst of devAsyn write errors at every `iocInit` for controls that work. |
| `AutoLevels` → histogram readback | second `setIntegerParam(function, value)` is a duplicate; `T_HISTOGRAM` goes stale (`tucsen.cpp:831`) | publishes `AxisSXR40Histogram` (`axisSXR40.cpp:1317`) | Bug in ADTucsen. |
| `FrameFormat` index | unchecked array index (`tucsen.cpp:804`) | bounds-checked, returns error (`axisSXR40.cpp:1204`) | A stale autosave value of 2 would index past ADAxisSXR40's 2-entry array; harmless in ADTucsen's 3-entry array. |
| `TECEnable` | absent | `TUIDC_ENABLETEC` set/get (`axisSXR40.cpp:1219-1279`) | Additive. |
| Temperature setpoint | `value + 50` (`tucsen.cpp:930`) | `value + 50` (`axisSXR40.cpp:1517`) | Same. |
| Everything else in `writeInt32` / `writeFloat64` | — | — | Identical logic. |

### 5.3 Camera info and connect

| Aspect | ADTucsen | ADAxisSXR40 | Impact |
|---|---|---|---|
| `TUCAM_VALUE_INFO.pText` for string ids | caller buffer of 1024 bytes (`tucsen.cpp:1033`, `:1058-1061`) | `NULL`; SDK returns its own pointer, copied out (`axisSXR40.cpp:1636`, `:1673`) | **The AXIS notes' claim that the buffer form leaves `Model`, `SDKVersion`, `FirmwareVersion` blank is wrong for this ADTucsen.** Verified 2026-09-10 on the running `XV4040:` IOC: `Model_RBV = Dhyana XF/XV4040BSI`, `SDKVersion_RBV = 2.0.7.0`, `FirmwareVersion_RBV = 2c022311292c01220509`. The PSI fix `6ee3e34` works. Both conventions are accepted by SDK 2.0.7.0. `differences-from-adtucsen.md` divergence 5 should be re-worded. |
| `TUIDI_BUS` dtype argument | 1 | 0 | No effect; `Bus` is special-cased before dtype is consulted. |
| `getcwd` result | unchecked | checked, falls back to `"."` (`axisSXR40.cpp:483`) | Hygiene. |
| Capability audit at connect | none | `reportCapabilitySupport()` probes 15 capabilities and 12 properties with `*_GetAttr`, logs a summary at `TRACE_ERROR` and per-id at `TRACE_FLOW` (`axisSXR40.cpp:584-650`) | Diagnostic. On this camera 8 of the inherited ids are unsupported. |

### 5.4 Temperature / telemetry poll (`tempTask`, 0.5 s)

| Aspect | ADTucsen | ADAxisSXR40 | Impact |
|---|---|---|---|
| `TemperatureActual` | raw `TUIDP_TEMPERATURE` value, published as-is under `ADBase`'s `EGU="C"` (`tucsen.cpp:894`) | `1.7 × raw + 15` (`axisSXR40.cpp:1430`), constants at `:92-96`; one-shot warning if raw leaves the fitted range [−25, 5] | **Different numbers on the same camera.** The raw value is not Celsius on this unit (AXIS factory test report p10). Raw ≈ −9 corresponds to ≈ −0.3 °C. The constants are **per-unit** (AXIS s/n 702 / KBSG09024003) and must be re-established if the camera is swapped. |
| `TransferRate` | polled | polled | Same. |
| Ring occupancy | not read | `TUIDI_CURRENTBUFFRAMES`, `TUIDI_TOTALBUFFRAMES` (`axisSXR40.cpp:1476-1482`) | Additive. Saturated at full frame (ring is always full), so not a useful early warning there. |
| Disable switch | none | env `AXIS_NO_TEMP_POLL` skips the thread (`axisSXR40.cpp:446`) | Diagnostic for the stop-deadlock investigation. |

### 5.5 Unchanged between the two

`imageGrabTask` control flow, `startCapture`/`stopCapture` (AbortWait → Cap_Stop →
Buf_Release), `getTrigger`/`setTrigger`, `getTriggerOut`/`setTriggerOut` including the
`triggerOutSupport_` probe of all 3 ports, `readEnum` and `getCapabilityText`,
`setProperty` clipping to the SDK-reported range, `setSerialNumber` via `TUREG_SN`,
`disconnectCamera`/`shutdown`, the iocsh registration and the 7-argument config signature.

---

## 6. IOC and configuration differences

**Which ADTucsen IOC.** The example IOC inside the checkout
(`ADTucsen/iocs/tucsenIOC/iocBoot/iocTucsen/st.cmd`, prefix `TUCSEN1:`) is *not* what
runs. The deployed IOC is `/usr/local/epics/iocs/xv4040/st.cmd`, started by
`ioc-xv4040.service` (systemd + procServ, `Restart=always`, log in
`/var/log/epics/xv4040.log`, documented in `/usr/local/epics/README.md`). An earlier
version of this section compared against the example file and reached wrong
conclusions (truncated image array, unbounded memory, no autosave); all three are
fixed in the deployed file. The table below is against the **deployed** IOC.

On 2026-09-10 our `st.cmd` was made a drop-in for the deployed IOC: same prefix and port
name, plus the settings from his file that were worth having. Settings where ours was
already the better choice were kept. The table shows the state after that change.

| | ADAxisSXR40 `iocAxisSXR40/st.cmd` | ADTucsen deployed `xv4040/st.cmd` | Note |
|---|---|---|---|
| `PREFIX` / `PORT` | `XV4040:` / `TUCSEN` | `XV4040:` / `TUCSEN` | **Same since 2026-09-10.** Clients cannot tell the drivers apart. |
| `XSIZE` / `YSIZE` | 4096 / 4096 | 4096 / 4096 | Same. |
| `NDStdArrays NELEMENTS` | 16777216 | 16777216 (via `$(NELEMENTS)`) | Same. |
| `NDStdArrays` queue | 5 | 3 | CA image is the fallback path; either is fine. |
| `QSIZE` | 21 | 5 | Kept ours: rides out a brief writer stall without dropping frames; the memory cap keeps it safe. |
| `CBUFFS` | 20 | 20 | Adopted his: 500 frames would be 16 GB. |
| `MAX_THREADS` | 8 | default (5) | Kept ours for faster statistics on 16 MP frames. |
| `maxMemory` | 2 GB | 2 GB | Adopted his. |
| `EPICS_CA_MAX_ARRAY_BYTES` | 40000000 | 40000000 | Adopted his; harmless under Base 7's auto array bytes. |
| `asynSetMinTimerPeriod(0.001)` | yes | no | Kept ours. |
| autosave | `commonPlugins.cmd` defaults plus our Db path, `$(CALC)/db`, status prefix, dated backups, 3 seq files every 300 s | explicit block: 7 request paths, `./autosave`, status prefix, dated backups, 3 seq files every 300 s | Adopted his backup settings; his three extra source-dir request paths are redundant with the installed `db/` copies already on ours. |
| `auto_settings.req` | `axisSXR40_settings.req` (which includes `ADBase_settings.req`), `NDStdArrays_settings.req`, `commonPlugin_settings.req` | `ADBase_settings.req`, `tucsen_settings.req` (which also includes `ADBase_settings.req`), `commonPlugin_settings.req` | Kept ours; his lists ADBase twice (37 duplicate entries) and omits NDStdArrays (19 PVs). Until 2026-09-11 ours also carried a stale local `commonPlugin_settings.req` that shadowed ADCore's and silently dropped 104 Codec/BadPixel/Proc1-TIFF settings; removed. Saved-PV counts are now 2373 (ours) vs 2354 unique (his). |
| Boot-time `dbpf` | `ArrayCallbacks` and `EnableCallbacks` for image1/Pva1/Stats1 **and** `FileTemplate` for TIFF/HDF/JPEG/netCDF | `ArrayCallbacks` and `EnableCallbacks` for image1/Pva1/Stats1 | Adopted his and kept ours. |
| Shebang line | yes | yes | Adopted; process name is `st.cmd` for both. |
| Camera XML | `Dhyana XFXV4040BSI_PIDe41b_KBSG09024003.xml` | same file | Same. |
| Host `usbfs_memory_mb` | documented in README | raised to 2000 via `/etc/modprobe.d` | Host-level; done. |
| Launcher | `start_epics.sh` with the same PVA/CA environment as his unit, or `info/systemd/ioc-axissxr40.service` (not enabled), console on 20001 | systemd unit with PVA environment, procServ console on 20000 | See `info/systemd/`. |
| `Manufacturer_RBV` | `Tucsen` | `Tucsen` | Driver string changed 2026-09-10; was `AxisSXR40`. |

Record-level differences that remain, both deliberate: our `FrameFormat` menu has no
`RGB888` (it stalls acquisition on this mono sensor), and our four extra records
(`TECEnable`, `TECEnable_RBV`, `BuffFrames_RBV`, `BuffTotal_RBV`) do not exist on his.

Live values read from the deployed IOC on 2026-09-10: `Model_RBV = Dhyana XF/XV4040BSI`,
`SDKVersion_RBV = 2.0.7.0`, `FirmwareVersion_RBV = 2c022311292c01220509`,
`MaxSizeX/Y_RBV = 4096`, `image1:ArrayData.NELM = 16777216`, `TemperatureActual = -2.81`
(raw), `SizeY_RBV = 32` (left by the August frame-rate sweep, restored by autosave).

Log history since 2026-08-10: 22 starts, no acquisition-time errors, 4 segfaults each
within seconds of an automatic restart following an abnormal death (3 of them during
the 2026-08-24/25 deadlock investigation, which was run on this service), 7 `SIGKILL`s
from that investigation. Cause of the restart segfaults not established; whether
ADAxisSXR40 shares them is unknown because it has not run under a supervisor.

---

## 7. Defects present in **both** drivers

These were not fixed on either side and behave the same.

1. **SDK calls made under the asyn port lock.** `TUCAM_Cap_Stop` in `stopCapture()`,
   the 0.5 s `TUCAM_Prop_GetValue` poll, and all property/capability writers run with
   the lock held. ADAxisSXR40's incident notes (`../incidents/stop-deadlock.md`) root-cause
   an IOC hang after high-rate stops to this, and confirm it reproduces on unmodified
   ADTucsen. Mitigated operationally by moving to a Renesas USB controller; the code is
   the same in both.
2. **`imageMode` read before assignment** in `imageGrabTask()`'s error branch
   (`tucsen.cpp:513`, `axisSXR40.cpp:766`). On the first failed grab after boot the
   variable is uninitialised.
3. ~~`TUIDC_VERTICAL` (`ReverseY`) does not take in either driver~~ **Corrected 2026-09-11:**
   the SDK applies the write and returns `NO_RESOURCE`. ADAxisSXR40's readback tolerance
   accepts it, so `ReverseY` round-trips; ADTucsen forces the value back to 0. A fork
   difference (§5.2), not a shared defect.
4. **8 unsupported parameters remain in the template** in both (`AutoExposure`,
   `GainMode`, `DefectCorrection`, `Enhance`, `BlackLevel`, `Brightness`, `Sharpness`,
   `HDRK`). ADAxisSXR40 keeps them deliberately and hides the widgets; ADTucsen shows them.
5. **`FlatCorrection` is exposed as an on/off** in both templates, but the SDK id is a
   4-step sequence (off / grab / calculate / enable). Neither driver walks the sequence.
6. `startTime` is computed and never used in `imageGrabTask()` in both.

---

## 8. Verdict

| Question | Answer |
|---|---|
| Same SDK, same camera, same parameter set? | Yes. Byte-identical SDK, 42 shared parameters, identical record names. |
| Same acquisition/trigger functionality? | Yes. The grab loop, start/stop, trigger-in and trigger-out code is the same. |
| Interchangeable for the AXIS-SXR-40? | **Yes, verified 2026-09-11** by `tests/compat/`: all 7529 PVs of the deployed ADTucsen IOC captured, our IOC compared PV by PV (record type, CA type, count, enum strings, PREC/EGU, identity values). Exactly seven differences, all intended: our four extra records, `FrameFormat` without RGB888 (×2), `TemperatureActual` PREC 2 vs 1. Zero unintended. Report: `tests/.results/compat-report.txt`; contract: `tests/compat/compat_rules.py`. The suite was also run against his IOC the same day (234 passed): the fork-fix tests that fail there are AutoLevels→Histogram readback, RGB888 rejection, ReverseY readback tolerance, and `SizeY`/`MinY` alignment; everything driver-agnostic passes on both. Before that: **Nearly.** The deployed `ioc-xv4040` is correctly sized and supervised. What differs is the driver: ADTucsen carries the ROI-clamp and AutoLevels bugs, applies no ROI alignment, and publishes the raw temperature. With our `st.cmd` set to the same prefix, port and sizing (see `info/systemd/`), clients cannot tell the two apart except for the four extra ADAxisSXR40 records and the missing `RGB888` choice. |
| Could ADTucsen be made equivalent? | By back-porting §5.2's two bug fixes, the ROI alignment, the handle `memset` and the `setCapability` readback tolerance. The temperature calibration, capability audit, TEC and ring counters would still be missing. |
| Anything ADTucsen does better? | It is generic (any Dhyana, colour included, Windows included) and self-contained (vendored SDK). ADAxisSXR40 is knowingly unit-specific: its temperature constants are tied to detector s/n 702. |

If the goal is one driver for the beamline, ADAxisSXR40 is the one to run against this
detector. If the goal is to upstream, the candidates that are camera-independent and
should go back to xiaoqiangwang/ADTucsen are: the ROI height clamp fix, the AutoLevels
histogram readback fix, zero-initialising the SDK handles and setting `uiRsdSize` before
`Buf_Alloc`, the `FrameFormat` bounds check, and the `setCapability` readback tolerance.
