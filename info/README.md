# ADAxisSXR40 — detector documentation

Everything here is about **this instrument and this driver**. Camera-generic and SDK
material deliberately stays in the companion `AXIS-SXR-40-SDK` repository
(internal, not published) — see [the split](#what-lives-where) below.

## Contents

| Item | What it is |
|---|---|
| [TODO.md](TODO.md) | Open problems, ordered by how much they block real use. Cited from `axisSXR40.cpp` and `axisSXR40.template` at the relevant call sites. |
| [known-gaps/](known-gaps/README.md) | The summary view: what is verified, what is unexercised, what is known-broken. Read before relying on a feature. |
| [dhyana-xfxv4040bsi.md](dhyana-xfxv4040bsi.md) | Exhaustive **measured** record of what this unit supports — every capability, property and vendor id probed against the camera, plus exposure grid, dark-frame baselines and throughput. The authority for the numbers hardcoded in the driver. |
| [porting/](porting/) | Every deliberate divergence from upstream ADTucsen, with the measurement behind each change. |
| [performance/](performance/) | Measured frame rate vs ROI, with the script that produced the numbers. |
| `manuals/` | The two AXIS detector manuals: USB User Manual (hardware, pinouts, trigger circuits) and the s/n 702 Test Report (factory acceptance, the temperature calibration). **Local working tree only — vendor copyright, excluded from the public repository.** |
| [labview-vs-epics-analysis/](labview-vs-epics-analysis/) | Audit of this driver against the ALS BCS LabVIEW driver for the same camera. Start with its `RISKS.md`. (The VI screenshots it cites are likewise excluded from the public repository.) |

## What lives where

The two trees split on **SDK vs detector**:

```
ADAxisSXR40/info/                    ← this instrument, this driver
├── TODO.md
├── known-gaps/                      verified vs unexercised vs known-broken
├── dhyana-xfxv4040bsi.md            measured capabilities of THIS unit
├── porting/                         divergences from upstream ADTucsen
├── performance/                     measured frame rate vs ROI
├── manuals/                         the 2 AXIS detector manuals (local only, not published)
└── labview-vs-epics-analysis/       driver-vs-BCS audit

AXIS-SXR-40/                         ← the SDK, camera-generic
├── info/ubuntu-setup.md             host SDK install
├── info/manuals/                    the 2 Tucsen SDK manuals + conversion toolchain
├── info/labview-sdk-manuals/        Tucsen LabVIEW SDK 2.1.10.0
├── sdk/                             TUCam C SDK, installer, provenance
└── examples/                        CameraProbe, ControlProbe, QtDemo, ADTucsen-upstream
```

Rule of thumb: if swapping in a different Dhyana camera would invalidate it, it belongs
here. If it would still be true, it belongs in the support repo.

One deliberate exception: `dhyana-xfxv4040bsi.md` is camera-level by title, but every
number in it was measured on **this** unit and several are hardcoded in
`axisSXR40.cpp` (the 10.32 µs row time, the 1.7/15 temperature calibration, the width
alignment of 8). It belongs with the code that depends on it.
