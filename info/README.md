# ADAxisSXR40 — detector documentation

Everything here is about **this instrument and this driver**. Camera-generic and SDK
material deliberately stays in the companion `AXIS-SXR-40-SDK` repository
(internal, not published) — see [the split](#what-lives-where) below.

Every document lives in a folder named for what it is about; this file is the only one
at the top level, and it is just the index.

## Contents

| Folder | What is in it |
|---|---|
| [pipeline/](pipeline/) | [acquisition-overview.md](pipeline/acquisition-overview.md) (figures in `pipeline/acquisition/`) — **how a frame gets from the sensor to the `.h5` file**: camera timing, USB, the SDK ring buffer, the driver's grab thread and its one copy, plugin queues, the HDF5 writer and the page cache; which thread does what, and where frames can be lost and whether anything sees it. Start here if you are new to the driver. |
| [camera/](camera/) | [dhyana-xfxv4040bsi.md](camera/dhyana-xfxv4040bsi.md) — exhaustive **measured** record of what this unit supports: every capability, property and vendor id probed against the camera, exposure grid, dark-frame baselines, throughput. The authority for the numbers hardcoded in the driver. [capabilities.md](camera/capabilities.md) — **which of the 26 SDK ids this camera actually implements** (11/15 capabilities, 8/12 properties), how that was determined, and how to decode the numeric ids in the startup error burst. Read before wondering why a control does nothing. |
| [known-gaps/](known-gaps/) | [README.md](known-gaps/README.md) — the summary view: what is verified, unexercised, or known-broken; read before relying on a feature. [TODO.md](known-gaps/TODO.md) — the open problems in full, with evidence and repro steps, ordered by how much they block real use; cited from `axisSXR40.cpp` and `axisSXR40.template` at the relevant call sites. |
| [incidents/](incidents/) | [report-detector-freeze-2026-08-25.md](incidents/report-detector-freeze-2026-08-25.md) — **start here if you are not a driver developer**: plain-language report of the freeze-after-fast-stop problem for management and infrastructure, with the evidence and the fix. [stop-deadlock.md](incidents/stop-deadlock.md) — the full technical write-up: gdb stacks, the three symptoms it masqueraded as, `usbmon` and `dmesg` evidence, recovery, the controller swap, and the driver hardening still worth doing. |
| [performance/](performance/) | Measured frame rate vs ROI height (the script that produced them is now `tests/performance/roi-rate-test.sh`). One dated results file per configuration, each holding only its own numbers ([physical host 2026-07-29](performance/2026-07-29-roi-frame-rate-physical.md); KVM guest with [ASMedia](performance/2026-08-25-roi-frame-rate-vm-asmedia-bl1101ad01.md) and with [Renesas](performance/2026-08-26-roi-frame-rate-vm-renesas-bl1101ad01.md) USB controllers), [comparison.md](performance/comparison.md) putting the three side by side, [2026-09-10 driver comparison](performance/2026-09-10-driver-comparison-vm-renesas-bl1101ad01.md) running the same sweep under ADAxisSXR40 and ADTucsen on the same host within the hour (identical throughput; the data path is the SDK's), and [tools/h5check](../tools/h5check/) for verifying what the files actually contain. |
| [porting/](porting/) | [differences-from-adtucsen.md](porting/differences-from-adtucsen.md) — every deliberate divergence from upstream ADTucsen, with the measurement behind each change. [ADAxisSXR40-vs-ADTucsen.md](porting/ADAxisSXR40-vs-ADTucsen.md) — side-by-side functional comparison against the ADTucsen checkout on this host (the PSI fork), code-diffed: shared parameters, what only one side has, bug fixes, IOC configuration, and the defects both still carry. |
| [testing/](testing/) | Dated one-page results of running the whole suite against both drivers on the same day: pass counts per category for ADAxisSXR40 and ADTucsen, the stress tier side by side, and what makes the two IOCs interchangeable. Written for management; the method is in `tests/`. [2026-09-14](testing/2026-09-14-two-driver-test-report.md) (clean symmetric run after the weekend power-off, health line in our unit) and [2026-09-11](testing/2026-09-11-two-driver-test-report.md) (first run). |
| [systemd/](systemd/) | [README.md](systemd/README.md) — running this IOC as a systemd service alongside Damon English's default `ioc-xv4040` (ADTucsen): why only one may run, install without enabling, the two-command driver swap each way, the start guard and where its refusals are logged, the clean-boot log baseline. [ioc-axissxr40.service](systemd/ioc-axissxr40.service) — the unit, a mirror of `ioc-xv4040.service` with paths, user, console port and log location changed. [ioc-axissxr40-run.sh](systemd/ioc-axissxr40-run.sh) — its `ExecStart`: runs the guard, starts procServ, and every minute reports the detector verdict as the unit's `Status:` line and as the watchdog heartbeat, so systemd restarts our IOC when the camera is present but the IOC is dead to it. [ioc-axissxr40-health.sh](systemd/ioc-axissxr40-health.sh) — that verdict (OK / CAMERA ABSENT / UNRESPONSIVE / ERROR / POLL FROZEN), also runnable by hand. [ioc-axissxr40-guard.sh](systemd/ioc-axissxr40-guard.sh) — refuses to start while `ioc-xv4040` is active/activating or pvAccess port 5075 is taken; reason goes to the journal and to `/var/log/areadetector/axisSXR40-guard.log`. |
| [../tests/](../tests/) | The functional test suite (pytest), run against the live IOC with `tests/run.sh`: `static/` needs no IOC (template vs driver, request files, startup files, docs, template diff vs ADTucsen); `boot/` reads the console log and autosave file; `pvs/` connects every record and round-trips the safe setpoints; `driver/` verifies the fork's fixes; `acquire/`, `image/`, `files/`, `robustness/`, `workflow/`, `performance/` exercise the camera; `compat/` compares against a recorded ADTucsen baseline; `stress/` is the opt-in sustained-load tier (`tests/run.sh stress`) whose `--record` runs land as dated files in `performance/`. Runs against Damon's IOC too, with his expectations. |
| [labview-vs-epics-analysis/](labview-vs-epics-analysis/) | Audit of this driver against the ALS BCS LabVIEW driver for the same camera. Start with its `RISKS.md`. (The VI screenshots it cites are excluded from the public repository.) |
| `manuals/` | The two AXIS detector manuals: USB User Manual (hardware, pinouts, trigger circuits) and the s/n 702 Test Report (factory acceptance, the temperature calibration). **Local working tree only — vendor copyright, excluded from the public repository.** |

## What lives where

The two trees split on **SDK vs detector**:

```
ADAxisSXR40/info/                    ← this instrument, this driver
├── README.md                        this index
├── pipeline/                        how acquisition works, sensor → .h5 (+ acquisition/ figures)
├── camera/                          what THIS unit implements, measured
├── known-gaps/                      verified vs unexercised vs known-broken; TODO.md
├── incidents/                       the 2026-08-25 freeze: report + technical write-up
├── performance/                     measured frame rate vs ROI, per configuration
├── porting/                         divergences from upstream ADTucsen; ADTucsen comparison
├── systemd/                         our service unit + how to swap drivers with ioc-xv4040
├── testing/                         dated test reports (both drivers, all categories)
├── labview-vs-epics-analysis/       driver-vs-BCS audit
└── manuals/                         the 2 AXIS detector manuals (local only, not published)

AXIS-SXR-40/                         ← the SDK, camera-generic
├── info/ubuntu-setup.md             host SDK install
├── info/manuals/                    the 2 Tucsen SDK manuals + conversion toolchain
├── info/labview-sdk-manuals/        Tucsen LabVIEW SDK 2.1.10.0
├── sdk/                             TUCam C SDK, installer, provenance
└── examples/                        CameraProbe, ControlProbe, QtDemo, ADTucsen-upstream
```

Rule of thumb: if swapping in a different Dhyana camera would invalidate it, it belongs
here. If it would still be true, it belongs in the SDK repository.

One deliberate exception: `camera/dhyana-xfxv4040bsi.md` is camera-level by title, but
every number in it was measured on **this** unit and several are hardcoded in
`axisSXR40.cpp` (the 10.32 µs row time, the 1.7/15 temperature calibration, the width
alignment of 8). It belongs with the code that depends on it.
