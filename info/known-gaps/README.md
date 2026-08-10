# Known gaps

What is verified, what is unexercised, and what is known-broken — read this
before relying on a feature in anger. The larger items have full write-ups with
evidence and repro steps in [TODO.md](../TODO.md); this file is the summary view.

- **Acquisition works end to end.** Single-frame and continuous full-frame
  acquisition verified against the camera (~9 fps sustained, zero dropped arrays,
  real 16-bit data), and TIFF and HDF5 both write valid files. Still unexercised:
  binned modes, ROI, HDF5 compression, and trigger modes from EPICS.
- **The SDK ring runs full whenever acquiring** — `AXIS_BUFF_FRAMES` sits pinned
  at 2, equal to `AXIS_BUFF_TOTAL`. Nothing is dropped, but there is no headroom,
  so describing ring occupancy as an "early warning" overstates it: the signal is
  saturated from the first frame. See [TODO.md](../TODO.md) §1.
- **`FileTemplate` defaults to empty**, which makes every file writer fail with a
  blank filename and a misleading `Error opening file , status=3`. Latent now that
  autosave holds a value, but it returns on a fresh `autosave/`.
- **TEC enable is reachable but has never been written.** Not tested unattended:
  the TEC's hot side depends on the detector's cooling loop, which no part of this
  software can see or verify. See [TODO.md](../TODO.md) §2.
- **The `.ui` screens are stale.** The `medm` `.adl` screens now match the camera —
  the 8 unsupported controls removed, `TECEnable` and the ring counters added — but
  `op/ui/autoconvert/*.ui` are generated files and need regenerating with `adl2ui`,
  which is not installed here. caQtDM users still see the old layout.
- **`medm` itself is not installed on the development host**, so
  `start_epics.sh`'s GUI half silently does nothing and only the IOC starts.
- ~~9 SDK functions unverified~~ — **now all verified working** by the
  `ControlProbe` utility (`examples/cpp/ControlProbe` in the companion
  `AXIS-SXR-40-SDK` repository), including the load-bearing `Buf_AbortWait`
  (IOC stop) and `Capa_SetValue` (binning). Results table in the
  characterisation notes ([dhyana-xfxv4040bsi.md](../dhyana-xfxv4040bsi.md),
  "Control path" section). Notable: 3 trigger-out ports exist, so that feature
  will be live here.
- **The 8 unsupported parameters are still in the `.template`**, though their
  controls are now off both `medm` screens. They stay in the database on purpose:
  the records are harmless, and `reportCapabilitySupport()` remains the
  authoritative statement of what this camera implements.
- **Trigger modes are untested.** This camera reports no `TUIDC_ENABLEOVERLAP`
  and no rolling-scan control, so any upstream trigger behaviour that assumed
  overlap will differ.
- **`getcwd` return value unchecked** at `axisSXR40App/src/axisSXR40.cpp:388` —
  inherited, emits a compiler warning, harmless but worth tidying.
