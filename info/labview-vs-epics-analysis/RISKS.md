# What to worry about: ADAxisSXR40 vs the LabVIEW BCS driver

Prioritised findings from the full seven-case audit of `Axis Photonique BCS Driver.vi`.
Evidence is in [labview-bcs-vs-epics-audit.tsv](labview-bcs-vs-epics-audit.tsv) (one row
per parameter) and [labview-bcs-parameters.txt](labview-bcs-parameters.txt) (narrative).

**Date:** 2026-08-05 · **Scope:** all 7 cases (Initialize, Init Single Shot, Start Single
Shot, Get Single Shot Status, Get Single Shot Data, Get Freerun Status, Shutdown)

---

## Bottom line

**No camera capability is out of reach.** Every parameter BCS writes, ADAxisSXR40 can
write. Nothing in the LabVIEW driver touches the hardware in a way we cannot.

The gaps are **orchestration and policy** — what BCS does *around* the parameters — not
missing access. That is the reassuring headline, and it is worth stating plainly before
the list below, because the list looks longer than the risk actually is.

Two things genuinely deserve attention. One is a subsystem; one is a semantic mismatch.

---

## Tier 1 — worry, and act

### 1. The shutter chain on Out 3

Four rows in the audit look independent but are one subsystem: the mechanical shutter
driven from camera trigger-output port 3. This is the only place where our driver is
meaningfully behind.

| # | What BCS does | What we do | Consequence |
|---|---|---|---|
| 1a | Reads the beamline global `CCD Camera Shutter Inhibit` and ANDs its negation into the shutter enable | Nothing — no equivalent input exists | An external veto on the shutter is **silently lost** when running from the IOC |
| 1b | Computes `OutWidth = ShutterTime×1000` and `DelayTime = max(0, readout_ms − ShutterTime_ms)×1000` | Exposes raw µs-scale PVs, no arithmetic | An operator must redo the calculation by hand, including the seconds↔microseconds conversion |
| 1c | Uses its own mode enum: **0 = active, 3 = off** | Uses raw `TUOPT_*`: **0 = Low (off), 3 = Exposure Start** | Copying BCS's numbers across produces **exactly the wrong behaviour**, with no error |
| 1d | Explicitly parks Out 3 (`OutMode` = off) before disconnecting | `disconnectCamera()` stops capture but leaves `nTgrOutMode` untouched | A shutter can stay asserted or keep pulsing **after the IOC exits** |

**Why this is the real risk and not a documentation nit:** the driver's own README
(`/opt/epics/synApps/support/areaDetector-R3-14/ADAxisSXR40/README.md`, line 16) lists
*"Not verified: external trigger-in, trigger-out pulses, TEC."* The subsystem BCS
leans on hardest is precisely the one our driver has **never had tested against
hardware**. Each of 1a–1d is individually cheap to fix; the exposure is that they are
unverified *and* they drive a physical shutter.

**Actions**
- [ ] **Scope Out 3 on the running BCS system.** One measurement resolves 1b, 1c and the
      "does our trigger-out work at all" question simultaneously. Do this first.
- [ ] Add the park-on-disconnect (1d). Small, clearly correct, no downside.
- [ ] Ask beamline staff what `CCD Camera Shutter Inhibit` guards (1a). If it protects
      anything physical, EPICS needs an equivalent interlock input before it takes over.
- [ ] Decide whether to add soft records that compute width/delay from a shutter time
      in msec (1b), or to document the arithmetic for operators.

### 2. Exposure time means something different

Not a missing feature — a **semantic mismatch**, which is worse because it is invisible.

`Init Single Shot` does not program the requested exposure. It programs:

```
rows       = Use ROI? ? Height : 4096
readout_ms = rows × 0.01032          # 0.01032 ms = one sensor row
CAMERA_EXPTM ← Timing.Exposure(sec) × 1000 + readout_ms
```

So a 100 ms full-frame single shot programs the camera for **142.3 ms**. We write
`AcquireTime` straight through.

Any attempt to reproduce beamline data or timing through EPICS will disagree, and
**nothing will look broken**.

**Action**
- [ ] Ask the BCS author whether the readout-time addition is deliberate physics or an
      old workaround. Do not copy it into the driver without knowing which — and do not
      compare images or frame rates against BCS until it is settled.

*Side benefit already banked:* BCS's hardcoded `0.01032` ms row time confirms our
documented 10.32 µs exposure step exactly.

---

## Tier 2 — verify, probably fine

- **Mid-acquisition ROI changes.** `Get Freerun Status` does
  `STOP → DELAY 1000 ms → TU_SetROI → TU_GetTrigger → TU_StartCapture` when any of five
  controls change. We call `setROI()` immediately while frames are flowing, with no stop
  and no settling delay. That 1 s delay looks like it was added after something went
  wrong. Worth one test if live ROI changes are used at the beamline.
- **`bEnable` hardcoded `true`.** LabVIEW's `TU_SetROI` takes an on/off flag; ours always
  passes enabled. Full-frame-with-ROI-enabled *should* equal ROI-disabled, but it is
  untested. Cheap to make conditional on the region being smaller than `MaxSizeX/Y`.
- **`FlatCorrection` is a PV that cannot work.** We expose it, but the LabVIEW SDK's
  `TU_SetShadingFrame` — the call that supplies the reference frame — has no counterpart
  in our driver. It returns `NO_RESOURCE` on this camera anyway, so this is a misleading
  control rather than a lost capability.

---

## Tier 3 — do not worry

**The BCS "DPC" mislabel.** Id 537 is `TULVIDC_NOISELEVEL` (noise-reduction level), not
defect-pixel correction — there is no defect-pixel id anywhere in the LabVIEW id space.
That is a bug on BCS's side, and our `DefectCorrection` PV is a no-op on this camera
regardless. It matters only as an instruction: **when matching beamline images, set
`NoiseLevel`, not `DefectCorrection`.**

**Everything in audit section 7.** Either areaDetector does it better, or the camera does
not support it:

| LabVIEW feature | Why it does not matter |
|---|---|
| Video recording (`TU_StartRecorder`) | Use NDFileHDF5 streaming |
| Multi-stream capture | No use case here |
| Frame index (`TU_GetFrameIndex`) | `ArrayCounter` / NDArray `uniqueId` |
| Image save path/format/name/count | NDFile plugins own file writing |
| `TUIDP_FRAME_RATE` | **Not supported** on this camera |
| Rolling scan, test image mode | **Not available** on this camera |
| LED, PGA gain, pixel clock enables | Not used by BCS either |

**Minor, cosmetic:** our trigger-out mode `mbbo` stops at `Readout End(5)`; the SDK also
defines `TUOPT_TRIREADY(6)`. `mbbo` has 16 slots, so adding it is trivial if ever wanted.

---

## One measurement to run first

Put a scope on **Out 3** with the BCS system acquiring. That single test resolves:

1. Which raw `TUOPT_*` value reproduces the beamline shutter pulse (3 Exposure Start, or
   4 Exposure Global)
2. Whether `OutWidth` really is microseconds pass-through (the guide states no unit)
3. Whether our trigger-out path works at all — currently unverified

Three of the four shutter unknowns, from one afternoon on the beamline.

---

## Open questions for other people

**For the BCS maintainer**
- Why is exposure inflated by the readout time? (Tier 1.2)
- Is the control labelled "Defect Pixel Correction" meant to be denoise, or was the wrong
  id picked? (Tier 3)
- Which `OutMode` value does the shutter boolean produce, and what does the subVI map it
  to? (Tier 1.1c)
- Notes elsewhere refer to id **772** for SAVE; every screenshot shows **771**
  (`TULVIDC_TRIGGERSAVE`; 772 is its sibling `TRIGGERBUFSAVE`). Different VI revision?

**For beamline staff**
- What does `CCD Camera Shutter Inhibit` protect? (Tier 1.1a)
- Are mid-scan ROI changes actually used? (Tier 2)
- Can we get a copy of `Axis Photonique Scan Setup.txt`? It holds the values the beamline
  really runs with — the reference for whether our autosave defaults match operations.

---

## Not a gap, but worth doing anyway

`TULVIDP_TEMPERATURETARGET` (327) → `TUIDP_TEMPERATURE_TARGET` (0x2B). Neither BCS nor we
use it, but our own capability probe found it **is** supported on this camera (range
0..100, default 30). It may be the clean way to resolve the `+50` setpoint offset
asymmetry our driver flags as unresolved.

Note BCS only ever *reads* temperature, so it offers no evidence either way on the write
scale. It does, however, **independently confirm the readback calibration**: BCS applies
`1.7*x + 15`, identical to our `AXIS_TEMP_CAL_SLOPE`/`OFFSET`. Two independent codebases
agreeing retires any doubt there.
