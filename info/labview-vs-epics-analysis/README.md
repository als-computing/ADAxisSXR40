# LabVIEW BCS vs EPICS areaDetector — analysis

Comparison of the ALS BCS LabVIEW driver (`Axis Photonique BCS Driver.vi`) against our
EPICS driver **ADAxisSXR40**, to establish that nothing the beamline relies on is missing
from the areaDetector implementation.

Both drivers control the same camera: Tucsen Dhyana XFXV4040BSI (USB `5453:e41b`,
s/n KBSG09024003) inside the AXIS-SXR-40 detector.

## Contents

| File | What it is |
|---|---|
| **[RISKS.md](RISKS.md)** | **Start here.** Prioritised "what should I actually worry about" — 2 things that matter, 3 to verify, the rest to ignore. |
| [labview-bcs-vs-epics-audit.tsv](labview-bcs-vs-epics-audit.tsv) | The full audit: one row per parameter, 99 rows, 9 columns (`BCS ID`, `Parameter`, `Description`, `EPICS`, `EPICS PV`, `EPICS RBV`, `Exists?`, `LV BCS State`, `Notes`). Tab-separated — opens directly in a spreadsheet. |
| [labview-bcs-parameters.txt](labview-bcs-parameters.txt) | Narrative companion: the decoded id space, per-VI call sequences, and the reasoning behind each finding. |
| [labview-screenshots/](labview-screenshots/) | Source material — block diagrams of all seven cases of the VI. |
| *(SDK — kept in the support repo)* | Tucsen LabVIEW SDK 2.1.10.0 — the vendor guides that decode the id space, plus the `TU_*.vi` library and `TULV_API.dll` the BCS driver calls. In the companion `AXIS-SXR-40-SDK` repository under `info/labview-sdk-manuals/`. |

## How this was derived

The block-diagram constants (`532`, `301`, `774`, `802`, `537`, `771`, …) are **not** TUCam
ids. They belong to a separate LabVIEW-layer id space (`TULVIDC_*` capabilities /
`TULVIDP_*` properties) that `TULV_API.dll` translates into the `TUIDC_*`/`TUIDP_*` ids our
driver uses. They were decoded from:

    AXIS-SXR-40-SDK repo: info/labview-sdk-manuals/Tucsen相机 Labview开发指南.pdf   §6.1.3, §6.1.4

The **Chinese** guide lists every id with its decimal value, which is exactly what the
diagram shows. The English guide's tables are an older, shorter subset and are missing
several ids used here — including `TECENABLE` (802) and `TRIGGERSAVE` (771). Use the CN
guide for any further decoding.

## Cases covered

All seven frames of the VI's case selector: `Initialize`, `Init Single Shot`,
`Start Single Shot`, `Get Single Shot Status`, `Get Single Shot Data`,
`Get Freerun Status`, `Shutdown`.

## Headline result

No camera capability is out of reach — every parameter BCS writes, ADAxisSXR40 can write.
The real risks are the shutter chain on trigger-output port 3 (four related gaps, in the
one subsystem our driver has never had verified against hardware) and a silent difference
in what "exposure time" means. See [RISKS.md](RISKS.md).
