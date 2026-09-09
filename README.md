# ADAxisSXR40 — EPICS areaDetector driver for the AXIS-SXR-40

Drives the **Tucsen Dhyana XFXV4040BSI** (USB `5453:e41b`) inside the AXIS-SXR-40
via Tucsen's TUCam SDK.

The SDK is **not GenICam-compliant** and the camera is not USB3 Vision, so
ADGenICam is not an option. Evidence is in `sdk/sdk-overview.md` §8 of the
AXIS-SXR-40 support repository.

| | |
|---|---|
| Driver source | [axisSXR40App/src/axisSXR40.cpp](axisSXR40App/src/axisSXR40.cpp) |
| Builds against | EPICS Base 7.0.10, areaDetector R3-14, asyn R4-45, at `/opt/epics` |
| SDK headers | `/usr/local/include/tucam` — installed, not vendored (see below) |
| SDK library | `libTUCam.so.1` in `/usr/lib/x86_64-linux-gnu`, linked as a system library |
| Status | **Working against the camera.** Full-frame, binned and ROI acquisition verified; TIFF and HDF5 (incl. zlib) writing verified; software trigger verified. Not verified: external trigger-in, trigger-out pulses, TEC. See Known gaps. |


## What this driver is actually talking to

Three nested pieces of hardware from two vendors, plus the SDK. Being loose about
which is which causes real confusion, so:

```
  AXIS-SXR-40 ······································· the DETECTOR
  │   beamline instrument; what this driver is named for
  │   owns: optics, cooling loop, vacuum, mounting
  │
  └── Tucsen Dhyana XFXV4040BSI ····················· the CAMERA
      │   USB 5453:e41b · s/n KBSG09024003
      │   vendor: Tucsen (Xintu Photonics)
      │   owns: exposure, gain, ROI, binning, TEC, triggering
      │
      └── GSENSE4040BSI ····························· the SENSOR
              4096 × 4096 (16 MP) · 16-bit mono
              back-side-illuminated sCMOS

                       ▲
                       │  USB 3.0 bulk transfer
                       │  SuperSpeed, 5 Gbps, ~289 MB/s measured
                       │
  ┌────────────────────┴───────────────────────────┐
  │  libTUCam.so.1  (TUCam SDK)  +  this driver    │ ·· the SOFTWARE
  │  Tucsen's library. Drives the CAMERA.          │
  │  Contains no knowledge of AXIS-SXR-40.         │
  └────────────────────────────────────────────────┘
```

**Everything this driver does is camera-level.** The SDK never reports the name
"AXIS" anywhere — it identifies itself as `Dhyana XF/XV4040BSI`, and that absence
is not a fault. Search Tucsen's documentation under the *camera* name; AXIS
documentation will not describe any of this API. Optics, cooling loop, vacuum and
beamline integration belong to the detector and are out of scope here.

The camera is the **XFXV** variant (`E41B`), *not* the plain `Dhyana 4040BSI`
(`E413`) — specs and firmware differ.

Practical consequences that shape the driver:

| | |
|---|---|
| Full frame | 4096 × 4096 × 16-bit mono → **32 MiB per frame** |
| Throughput | ~289 MB/s measured → **≈8.6 fps** at full frame |
| SDK frame ring | **2 frames**, ~230 ms of slack — and it sits *full* whenever acquiring at full frame, so occupancy is not a useful warning signal. Depth is not adjustable. |
| Binning | via `TUIDC_RESOLUTION` (2048², 1024²), *not* the binning capabilities |
| Exposure | 10.32 µs → 3600 s, in 10.32 µs steps (one sensor row time) |
| Sensor temperature | **`TemperatureActual` is not in °C** — it is raw, `EGU="raw"`. Real °C ≈ `1.7 × value + 15` (AXIS test report p10). The ≈ −9.5 previously recorded here was that raw value read as Celsius; it is about **−1 °C**. The *setpoint* (`Temperature`) *is* in °C — the driver adds the documented +50 offset. |

## Why the module is named for the detector

Deliberate, and worth stating because it cuts against convention. Most
areaDetector modules are named for an SDK (`ADGenICam`, `ADPvCam`, `ADSpinnaker`),
a camera family (`ADEiger`, `ADPilatus`, `ADLambda`) or a vendor (`ADAndor`,
`ADEuresys`) — essentially none for a single specific unit. And the code here only
speaks TUCam; it knows nothing about AXIS.

The detector name wins anyway because **that is what beamline staff call this
thing**, and an IOC named after the instrument on the floor is easier to find than
one named after the camera module inside it. Trade-off accepted: if a second AXIS
detector arrives with a different camera inside, this module won't cover it and
the name will read as a promise it can't keep. Rename to `ADDhyana` or `ADTUCam`
at that point.

## The TUCam SDK dependency

This module contains **no copy of the Tucsen SDK**. It compiles and links against
one installed system-wide:

| | Location |
|---|---|
| Headers — `TUCamApi.h`, `TUDefine.h` | `/usr/local/include/tucam` |
| Library — `libTUCam.so.1` | `/usr/lib/x86_64-linux-gnu` |

Both are placed there by the SDK installer, `sdk/install.sh` in the AXIS-SXR-40
support repository, which also builds the SONAME chain and runs `ldconfig`.
`sdk/check.sh` verifies the whole installation, headers included.

The SDK itself comes from Tucsen. The Linux package this driver was developed
against is
[`ubuntu18.04_20240628.tar.zip`](https://www.tucsen.com/uploads/ubuntu18.04_20240628.tar.zip);
current releases for all platforms are on Tucsen's
[download page](https://www.tucsen.com/download-software/).

**Why installed rather than vendored.** One installed set means nothing can drift
out of step with the library it declares. A stale local header copy still
*compiles* — the mismatch then surfaces as unexplained runtime behaviour rather
than a build error, which is much harder to diagnose. `check.sh` compares the
installed headers byte-for-byte against the SDK source so drift is reported
instead of discovered.

Consequences worth knowing:

- **Do not add `TUCamApi.h` / `TUDefine.h` to this module.** To build against a
  different SDK version, install that version.
- The SDK must be installed **before** this module will build. A missing header
  is the first thing to check if the compile fails.
- Paths are set in [configure/CONFIG_SITE](configure/CONFIG_SITE)
  (`TUCAM_INCLUDE`, `TUCAM_EXTERNAL`). Override in `configure/CONFIG_SITE.local`
  rather than editing that file.
- The SDK is proprietary Tucsen material under Tucsen's own terms; it is not
  covered by this module's LICENSE.

## Prerequisites

Build the stack in this order, and prove each layer works before adding the
next — a fault found at the right layer takes minutes to diagnose; the same
fault found two layers up takes days.

1. **EPICS Base 7** — <https://epics-controls.org/resources-and-support/base/>.
   This driver is developed against **7.0.10**. Set
   `EPICS_HOST_ARCH=linux-x86_64` and confirm a base binary (e.g. `softIoc`)
   runs.
2. **synApps support modules** — <https://github.com/EPICS-synApps/support>.
   The versions this driver builds against are pinned in
   [configure/RELEASE](configure/RELEASE): asyn R4-45, autosave R6-0,
   busy R1-7-4, calc R3-7-5, sequencer R2-2-9, sscan R2-12, iocStats 4-0-1.
3. **areaDetector R3-14** — <https://github.com/areaDetector/areaDetector> —
   with **ADCore** and **ADSupport** built.
4. **Prove the stack with ADSimDetector before touching this module.** Build
   [ADSimDetector](https://github.com/areaDetector/ADSimDetector), run its
   example IOC, start acquisition, and confirm images arrive (view them in
   ImageJ/caQtDM/medm, or just watch `caget ...cam1:ArrayCounter_RBV` count
   up). ADSimDetector needs no hardware and no vendor SDK, so it isolates the
   EPICS/areaDetector half of the stack completely: if the simulated camera
   does not acquire, this driver will not either, and the fault is in the
   EPICS installation, not here.
5. **The Tucsen TUCam SDK, installed system-wide** — see
   [the section above](#the-tucam-sdk-dependency) for what goes where and
   where to download it.
6. **The camera on USB 3.0**, visible as ID `5453:e41b` in `lsusb`. Raise
   `usbfs_memory_mb` from its 16 MB default — one full frame is 32 MiB — see
   [info/known-gaps/TODO.md](info/known-gaps/TODO.md).

## Build

Clone as `ADAxisSXR40` next to the other areaDetector modules — the paths in
[configure/RELEASE](configure/RELEASE) assume `$(AREA_DETECTOR)/ADAxisSXR40`:

```bash
cd /path/to/areaDetector-R3-14
git clone https://github.com/als-computing/ADAxisSXR40.git
cd ADAxisSXR40
export EPICS_HOST_ARCH=linux-x86_64
make
```

If your module paths differ, override them in `configure/RELEASE.local`
(and `configure/CONFIG_SITE.local` for SDK paths) rather than editing the
tracked files. The SDK must be installed system-wide **before** building,
because `CONFIG_SITE` sets `TUCAM_EXTERNAL = YES` — the driver links the
installed `libTUCam` rather than staging a private copy, so a stale bundled
SDK can never shadow the real one.

Produces `lib/linux-x86_64/libaxisSXR40.so`, installs `axisSXR40.template`
into `db/`, and builds the example IOC,
`iocs/axisSXR40IOC/bin/linux-x86_64/axisSXR40App`.

### Run the example IOC

```bash
cd iocs/axisSXR40IOC/iocBoot/iocAxisSXR40
../../bin/linux-x86_64/axisSXR40App st.cmd
```

Read the capability summary the IOC prints at startup —
`reportCapabilitySupport()` probes every parameter the driver drives and is
the authoritative statement of what the connected camera implements.

## What differs from ADTucsen

This driver started from upstream
[ADTucsen](https://github.com/djvine/ADTucsen) and diverged only where
measurement said it had to: a frame-wait timeout that follows the exposure
(this camera exposes up to 3600 s), two upstream bugs fixed (an ROI clamp that
wrote height into the width parameter, and a text-info calling convention that
left model/SDK/firmware blank), TEC-enable and ring-telemetry parameters
added, ROI alignment matched to the camera's real — asymmetric — rules, a
startup capability audit (8 of the 26 inherited parameters are unimplemented
on this model), and a link-order fix without which the IOC segfaults before
`iocInit`.

The full list, with the evidence behind each change:
[info/porting/differences-from-adtucsen.md](info/porting/differences-from-adtucsen.md).

## SDK calls the vendor GUI uses and this driver does not

Deliberate, but worth knowing they exist:

| Call | Why we skip it |
|---|---|
| `TUCAM_Vendor_ConfigEx(0, TUVCMEX_VENDOR)` | Unlocks the `TUIDV_*` vendor/factory properties (4 of 28 supported here). The GUI calls it **before `Dev_Open`**. If you ever need those ids, that ordering is mandatory. |
| `TUCAM_File_SaveImage` | SDK-side TIF/PNG/RAW writing. areaDetector's `NDFileTIFF`/`NDFileHDF5` plugins are the right layer for this, and give you HDF5 the SDK can't. |
| `TUCAM_Buf_CopyFrame` | Re-fetches the frame you hold in another `ucFormatGet`. Unnecessary here: `RAW` and `USUAl` are bit-identical on this camera (measured). |
| `TUCAM_Prop_GetValueText` | Enumerated labels for *properties*. Every supported property here is continuous, so there are no labels to fetch. |
| `TUCAM_Index_GetColorTemperature` | Colour cameras only; this sensor is mono. |

## Known gaps

What is verified, what is unexercised, and what is known-broken is tracked in
[info/known-gaps/](info/known-gaps/README.md) — read it before relying on a feature
in anger. Headline: full-frame acquisition and TIFF/HDF5 writing are verified
against the camera; external triggering and TEC control are implemented but
have never been exercised. The larger open problems, with evidence and repro
steps, are in [info/known-gaps/TODO.md](info/known-gaps/TODO.md).
