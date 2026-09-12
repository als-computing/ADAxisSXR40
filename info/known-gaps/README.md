# Known gaps

What is verified, what is unexercised, and what is known-broken — read this
before relying on a feature in anger. The larger items have full write-ups with
evidence and repro steps in [TODO.md](TODO.md); this file is the summary view.

- **The camera was delivering a synthetic test ramp, not sensor data, on 2026-08-26.**
  Every frame of the Renesas benchmark and every probe afterwards (50 ms, 1 s, 5 s;
  `Raw` and `Usual`) is a 256-level ramp in the high byte — min 0, max 65280, mean
  exactly 32640.0 — where a dark frame should read ~68 ADU with noise. Generated inside
  the camera; independent of exposure, format and driver. Unknown since when: nothing on
  this VM looked at pixel values before that day. Frame-rate and loss measurements
  stand (right size, real path); image content from this VM does not. Power-cycle and
  re-check with `tools/h5check` before trusting any image. [TODO.md](TODO.md) §8.
  **Still present 2026-09-10** under ADAxisSXR40 started by `ioc-axissxr40.service`
  (Renesas controller, after the VM reboots and card remap): 10-frame HDF5 stream, every
  frame min 0 / max 65280 / mean 32640.0, unique ids contiguous, 8.7 fps. Same camera
  state under both drivers, so the fix is not in software.
  **Gone on 2026-09-11, without a power cycle.** `tests/image/` saw the ramp at 15:50 and
  real sensor data at 16:10 (min 251, max 39132, mean 1650, sigma 182, frames differing).
  In between, the first full-tier test run had cycled `BinMode` 1 → 2 → 0
  (`TUIDC_RESOLUTION`) and stopped/started acquisition 20 times at 32 rows. The binning
  cycle is the prime suspect for clearing the camera's internal test mode; not yet
  reproduced deliberately. The mean of ~1650 ADU is far above the ~68 ADU dark baseline
  in the characterisation notes, so either the sensor is lit or its offset moved:
  `tests/image/test_dark_frame.py::test_dark_frame_mean_is_tens_of_adu` stays an expected
  failure until someone checks at the detector.

- **`Acquire=0` after high-rate acquisition can deadlock the IOC.** Seen at 128, 32 and
  8 rows; not in 20 stops at ≥ 256. After the stop the camera stops completing USB
  transfers and whichever SDK call is in flight under the asyn port lock hangs —
  `TUCAM_Cap_Stop` in `stopCapture()`, or the 0.5 s temperature poll's
  `TUCAM_Prop_GetValue` — so the driver goes silently dead: `DetectorState` may read
  `Acquire` *or* `Idle`, writes queue forever, no frames reach any plugin, `exit` hangs, and
  the only way out is `SIGKILL` plus a VM reboot (the camera has already stopped
  answering by then).
  Root-caused with gdb 2026-08-25 (three shapes, one cause); the fix is to make **no** SDK
  call while holding the port lock — `Cap_Stop`, the temperature poll, and the
  property/capability writers alike. **Confirmed identically on upstream ADTucsen** (1 of 1, first stop at 32
  rows) — the SDK's stop path, not this driver. `usbmon` + `dmesg` (14:42) place the fault below
  the SDK: the ASMedia xHCI controller (PCI passthrough) mishandles the URB cancellation
  storm of an un-commanded stop, and the camera's control endpoint is dead afterwards.
  The temperature poll was tested as a possible
  cause (disabled — the next SDK call, an exposure write, hung instead): it is a
  victim. **Resolved operationally 2026-08-25 16:31 by moving the detector to a Renesas
  uPD720202 controller (still passthrough): 38 of 38 stops clean across every height
  including 8 rows; acquire-only frame rates now match bare metal.** The driver hardening remains worth doing. Full write-up: [stop-deadlock.md](../incidents/stop-deadlock.md);
  [TODO.md](TODO.md) §1.

- **OPEN AUDIT — measurements taken before RELEASE change 9 may be invalid.**
  Change 9 found that the `T_*` → `AXIS_*` rename had left the template referring
  to parameters that no longer existed, so **42 of the 45 camera parameters were
  inert**: writing them did nothing, and the failure was silent from the operator's
  side because only `ADBase.template` records still worked. Any measurement made
  before that fix, which relied on setting a camera-specific parameter, measured
  the camera in its *default* state rather than the state the notes claim.

  **Unaffected** (these are `ADBase` records and always worked): exposure time,
  ROI/`ADSizeX`/`ADSizeY`/`ADMinX`/`ADMinY`, image geometry, temperature readback,
  model/SDK/firmware strings, frame counters and rates. So the ROI alignment rule
  (divergence 7) and the frame-rate-versus-ROI-height table stand.

  **To re-verify** — each of these is set through an `AXIS_*` parameter:

  | Claim | Parameter | Where |
  |---|---|---|
  | "full frame, 2×2 and 4×4 binned" passed the size check | `AXIS_BIN_MODE` | divergence 2; RELEASE change 14 |
  | `TUIDC_BITOFDEPTH` offers only 16 | `AXIS_BIT_DEPTH` | RELEASE change 14 |
  | RGB888 stalls acquisition and does not recover | `AXIS_FRAME_FORMAT` | RELEASE change 14; `frameFormats[]` |
  | ring occupancy varies at 1000×600, ~80 fps | `AXIS_BIN_MODE` (if binned) | divergence 4 |

  If a binning request was inert, the camera stayed at full frame and "2×2 and 4×4
  binned passed the check" reduces to the full-frame case tested three times over.
  That would not make the conclusion wrong, but it would leave it unevidenced.

  **First step is to establish the date change 9 landed** and compare it against
  the `2026-07-29` measurement runs; the repository has a single commit, so the
  ordering cannot be recovered from git history. If change 9 predates those runs,
  strike this item.

- **Acquisition works end to end.** Single-frame and continuous full-frame
  acquisition verified against the camera (~9 fps sustained, zero dropped arrays,
  real 16-bit data), and TIFF and HDF5 both write valid files. Still unexercised:
  binned modes, ROI, HDF5 compression, and trigger modes from EPICS.
- **The SDK ring runs full whenever acquiring** — `AXIS_BUFF_FRAMES` sits pinned
  at 2, equal to `AXIS_BUFF_TOTAL`. Nothing is dropped, but there is no headroom,
  so describing ring occupancy as an "early warning" overstates it: the signal is
  saturated from the first frame. Why the depth cannot be raised: [RELEASE.md](../../RELEASE.md) change 11.
- **`FileTemplate` defaults to empty**, which makes every file writer fail with a
  blank filename and a misleading `Error opening file , status=3`. Latent now that
  autosave holds a value, but it returns on a fresh `autosave/`.
- **TEC enable is reachable but has never been written — and the cooler is
  already running regardless.** `TUIDC_ENABLETEC` reads `0` while the sensor sits
  well below ambient (−9.5 °C on 2026-07-29, −3.1 °C on 2026-08-24), so the
  capability is decoupled from actual cooler state and the Peltier runs from
  camera power-on. The coolant dependency is therefore a standing condition of
  having the camera powered, **not** something this control switches on — which
  makes it a beamline interlock question, not a driver one. No part of this
  software can see or verify the loop. See [TODO.md](TODO.md) §2.
- **The `.ui` screens are stale.** The `medm` `.adl` screens now match the camera —
  the 8 unsupported controls removed, `TECEnable` and the ring counters added — but
  `op/ui/autoconvert/*.ui` are generated files and need regenerating with `adl2ui`,
  which is not installed here. caQtDM users still see the old layout.
- **No screen launcher of our own.** `start_epics.sh` used to try to open `medm`,
  which is not installed as a package here; that half was removed on 2026-09-10 when the
  script became a pure IOC launcher mirroring `ioc-xv4040`'s environment. Damon's
  `medm-xv4040` launcher (a from-source MEDM under `/usr/local/epics/extensions`) opens
  the ADTucsen screen with `P=XV4040:,R=cam1:` and works against this IOC too, since
  the record names are the same; only our four extra records are missing from it.
- ~~9 SDK functions unverified~~ — **now all verified working** by the
  `ControlProbe` utility (`examples/cpp/ControlProbe` in the companion
  `AXIS-SXR-40-SDK` repository), including the load-bearing `Buf_AbortWait`
  (IOC stop) and `Capa_SetValue` (binning). Results table in the
  characterisation notes ([dhyana-xfxv4040bsi.md](../camera/dhyana-xfxv4040bsi.md),
  "Control path" section). Notable: 3 trigger-out ports exist, so that feature
  will be live here.
- **The 8 unsupported parameters are still in the `.template`** — full per-id
  table and method in [capabilities.md](../camera/capabilities.md), though their
  controls are now off both `medm` screens. They stay in the database on purpose:
  the records are harmless, and `reportCapabilitySupport()` remains the
  authoritative statement of what this camera implements.
- **Trigger modes are untested.** This camera reports no `TUIDC_ENABLEOVERLAP`
  and no rolling-scan control, so any upstream trigger behaviour that assumed
  overlap will differ.
- **`getcwd` return value unchecked** at `axisSXR40App/src/axisSXR40.cpp:388` —
  inherited, emits a compiler warning, harmless but worth tidying.
- **`cam1:TimeStamp_RBV`, `cam1:EpicsTSSec_RBV`/`EpicsTSNsec_RBV` and `cam1:UniqueId_RBV`
  stay at 0.** Found by `tests/acquire/test_timestamps.py` (2026-09-11). The driver stamps
  every NDArray correctly (the plugins' `image1:TimeStamp_RBV` etc. advance and track the
  host clock, and HDF5 files carry the timestamps), but never calls
  `setDoubleParam(NDTimeStamp)` / `setIntegerParam(NDUniqueId, NDEpicsTSSec, NDEpicsTSNsec)`
  after a frame, so the camera record's own copies are never published. Inherited from
  ADTucsen, identical there. Small fix in `imageGrabTask()` after `grabImage()`; the test
  is an expected failure until then.
- **`ReverseY` 'does not take' was ADTucsen behaviour, not the camera's.** The SDK
  answers the `TUIDC_VERTICAL` write with `TUCAMRET_NO_RESOURCE` but applies it. Our
  `setCapability()` verifies by readback and accepts, so `ReverseY` round-trips 1 and 0 on
  ADAxisSXR40; ADTucsen treats the code as failure and forces the parameter back to 0, so
  its readback stays 0. Both measured 2026-09-11 by `tests/driver/test_fixes.py::
  test_reversey_roundtrip` (passes on ours, xfails on his). Supersedes TODO §3's reading.
- **ROI alignment: the camera rounds width (8) and `MinX` (4) itself; it does NOT round
  `SizeY` or `MinY`.** Running `tests/driver/test_roi.py` on ADTucsen (2026-09-11): the
  width and MinX tests pass there too (camera rounding), while `SizeY` 1006 and `MinY` 14
  go through unaligned. Only the height/offset-Y alignment is our driver's contribution.
- **The upstream height-clamp bug is masked.** ADTucsen's `setROI` writes the clamped
  height into `ADSizeX`, but then calls `Cap_SetROI` with the correct local width and
  overwrites `ADSizeX` from `Cap_GetROI`, so EPICS never sees the corruption
  (`test_height_clamp_does_not_touch_width` passes on both drivers). The fork's fix is a
  correctness fix, not a behaviour change.
- **`Pva1:Image` monitors with a sub-field request never update.** `pvmonitor -r
  'field(uniqueId)' XV4040:Pva1:Image` prints the value at connect and nothing more while
  frames flow (checked 2026-09-11 with `field(uniqueId)`, `field(value)`, `record[queueSize=4]`);
  the full request receives every frame, and a QSRV record (`cam1:ArrayCounter_RBV`) updates
  with either request. NDPluginPva / pvDatabase behaviour in ADCore R3-14, identical for
  both IOCs. Viewers use the full request and are unaffected; scripts that want a cheap
  frame counter over pvAccess must subscribe to the whole NTNDArray (`tests/helpers/pva_viewer.py`).
- **Starting a continuous acquisition allocates ~256 MB once** (RSS 587 → 843 MB within the
  first 30 s at full frame, flat afterwards, released at stop; 8 × 32 MiB, the SDK's
  transfer buffers rather than the NDArrayPool, whose `PoolUsedMem` does not move). Not a
  leak: `tests/stress/test_long_continuous.py` measures growth from its first sample and
  records the start-up allocation. Size the VM with this on top of `maxMemory`.
