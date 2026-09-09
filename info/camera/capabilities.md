# Camera capabilities — what this camera implements, and how we know

Verified **2026-08-25** on host `bl1101ad01` against the camera this module is
written for:

| | |
|---|---|
| Model | `Dhyana XF/XV4040BSI` |
| Serial | `KBSG09024003` |
| SDK | `2.0.7.0` |
| Firmware | `2c022311292c01220509` |

**Result: 11 of 15 capabilities and 8 of 12 properties are implemented.** Seven
of the 26 ids the driver drives are absent, plus one that is present but whose
writes do not take — see [Three ways an id can fail](#three-ways-an-id-can-fail).

---

## Why this document exists

The TUCam SDK has **no "list what you support" call.** There is no enumeration
API, no capability bitmask, nothing to ask. The only way to discover whether a
control exists on a given camera is to call `GetAttr` on it and see whether it
fails.

That would be a minor annoyance except for one thing: **an unsupported `Set`
fails silently.** You write a value, the call returns, nothing happens, and
nothing tells you. Without a deliberate probe you would spend an afternoon
wondering why an EPICS control has no effect on the image.

So `reportCapabilitySupport()` runs at connect, probes every id the driver
drives, and logs a one-line summary at every IOC start. Because it is generated
from the hardware on every boot, it cannot go stale the way a hand-maintained
list can. This file is the human-readable version of that output.

## Method

Two probes, matching the SDK's two id namespaces:

| Group | SDK call | What it covers |
|---|---|---|
| Capabilities (`TUIDC_*`) | `TUCAM_Capa_GetAttr` | discrete / enumerated features |
| Properties (`TUIDP_*`) | `TUCAM_Prop_GetAttr` | continuous numeric values |

An id counts as **supported** when `GetAttr` returns `TUCAMRET_SUCCESS`. The
probe is read-only — it never writes to the camera — so it is safe to run at
every connect and safe to re-run at any time.

Source: `reportCapabilitySupport()` in
[`axisSXR40App/src/axisSXR40.cpp`](../../axisSXR40App/src/axisSXR40.cpp).

---

## Capabilities — 11 of 15

| id | | EPICS control | Status |
|---|---|---|---|
| `TUIDC_RESOLUTION` | `0x00` (0) | `BinMode` | supported |
| `TUIDC_PIXELCLOCK` | `0x01` (1) | `FrameSpeed` | supported |
| `TUIDC_BITOFDEPTH` | `0x02` (2) | `BitDepth` | supported |
| `TUIDC_HORIZONTAL` | `0x04` (4) | `ReverseX` | supported |
| `TUIDC_VERTICAL` | `0x05` (5) | `ReverseY` | supported — **but writes do not take**, see below |
| `TUIDC_FAN_GEAR` | `0x07` (7) | `FanGear` | supported |
| `TUIDC_ATLEVELS` | `0x08` (8) | `AutoLevels` | supported — returns `NO_RESOURCE`, applies anyway |
| `TUIDC_HISTC` | `0x0A` (10) | `Histogram` | supported — returns `NO_RESOURCE`, applies anyway |
| `TUIDC_ENHANCE` | `0x0C` (12) | `Enhance` | **NOT SUPPORTED** |
| `TUIDC_DFTCORRECTION` | `0x0D` (13) | `DefectCorrection` | **NOT SUPPORTED** |
| `TUIDC_ENABLEDENOISE` | `0x0E` (14) | `Denoise` | supported |
| `TUIDC_FLTCORRECTION` | `0x0F` (15) | `FlatCorrection` | supported — returns `NO_RESOURCE`, applies anyway |
| `TUIDC_IMGMODESELECT` | `0x16` (22) | `GainMode` | **NOT SUPPORTED** |
| `TUIDC_ENABLETEC` | `0x3B` (59) | `TECEnable` | supported — **but decoupled from the cooler**, see below |
| `TUIDC_ATEXPOSURE` | `0x03` (3) | `AutoExposure` | **NOT SUPPORTED** |

> **`FLTCORRECTION` is supported; `DFTCORRECTION` is not.** Flat-field works,
> defect correction does not. The names are one letter apart in the same family
> and are very easy to conflate.

## Properties — 8 of 12

| id | | EPICS control | Status |
|---|---|---|---|
| `TUIDP_GLOBALGAIN` | `0x00` (0) | `Gain` | supported |
| `TUIDP_EXPOSURETM` | `0x01` (1) | `AcquireTime` | supported |
| `TUIDP_BRIGHTNESS` | `0x02` (2) | `Brightness` | **NOT SUPPORTED** |
| `TUIDP_BLACKLEVEL` | `0x03` (3) | `BlackLevel` | **NOT SUPPORTED** |
| `TUIDP_TEMPERATURE` | `0x04` (4) | `Temperature` (setpoint, +50 offset) | supported |
| `TUIDP_SHARPNESS` | `0x05` (5) | `Sharpness` | **NOT SUPPORTED** |
| `TUIDP_NOISELEVEL` | `0x06` (6) | `NoiseLevel` | supported |
| `TUIDP_HDR_KVALUE` | `0x07` (7) | `HDRK` | **NOT SUPPORTED** |
| `TUIDP_GAMMA` | `0x08` (8) | `Gamma` | supported |
| `TUIDP_CONTRAST` | `0x09` (9) | `Contrast` | supported |
| `TUIDP_LFTLEVELS` | `0x0A` (10) | `LeftLevel` | supported |
| `TUIDP_RGTLEVELS` | `0x0B` (11) | `RightLevel` | supported |

The 8 unimplemented ids in one line: **auto-exposure, CMS/HDR image mode, defect
correction, enhance, black level, brightness, sharpness, HDR-K.**

---

## Three ways an id can fail

Lumping these together is what makes the SDK confusing. They are genuinely
different and need different responses.

**1. Absent — `GetAttr` fails, returns `TUCAMRET_NOT_SUPPORT` (`0x80000312`).**
The camera does not have the control. Nothing to do; the EPICS record exists but
writes will be rejected. These are the 7 marked NOT SUPPORTED above.

**2. Present, writes return `TUCAMRET_NO_RESOURCE` (`0x80000102`), and work
anyway.** `TUIDC_ATLEVELS`, `TUIDC_HISTC` and `TUIDC_FLTCORRECTION` all do this.
`NO_RESOURCE` is not even in `Capa_SetValue`'s documented error list (guide
5.3.3.3), and the SDK reuses it elsewhere to mean "the pFrame pointer is empty" —
it is a loosely applied internal code, not a diagnostic. Measured 2026-07-29:
writing AutoLevels 1/2/3 and FlatCorrection 1/2/3 all returned `NO_RESOURCE`, and
an independent `Capa_GetValue` read back exactly the requested value every time.

`setCapability()` therefore **verifies by readback and ignores the return code**
when the camera reads back what was asked. Without that, every `iocInit` produced
a burst of write errors for controls that actually work — which trains people to
ignore the log.

**3. Present, write returns an error, and genuinely does not take.**
`TUIDC_VERTICAL` (`ReverseY`) is the only one. `GetAttr` finds it, the vendor
documentation gives it as `[0, 1]` supported across the whole Dhyana series with
no precondition, but writing 1 returns `NO_RESOURCE` **and** the readback stays 0.
`ReverseX` was never observed to fail, so it is specifically the vertical mirror —
probably unimplemented in this firmware. Low priority: image orientation is
trivially fixed downstream. See [TODO.md](../known-gaps/TODO.md) §3.

### And one that is "supported" but means nothing

`TUIDC_ENABLETEC` passes the audit, yet the vendor capability table marks it
**unsupported** on 4040/4040BSI, and it is demonstrably decoupled from the actual
cooler: it reads `0` while the sensor sits well below ambient (−9.5 °C on
2026-07-29, −3.1 °C on 2026-08-24). The Peltier runs from camera power-on
regardless. **`GetAttr` succeeding is not proof a capability is usable.** Full
discussion at the call site in the driver and in
[known-gaps](../known-gaps/README.md).

---

## Decoding the startup error burst

Every IOC start logs a run of `setCapability` / `setProperty` failures. This is
autosave restoring values into ids the camera does not implement — harmless, but
alarming on first sight, and the messages print **numeric ids**, not names. Use
the tables above, or this shortcut for the ones you will actually see:

| Log message | Meaning |
|---|---|
| `capability 3` | `TUIDC_ATEXPOSURE` — absent |
| `capability 12` | `TUIDC_ENHANCE` — absent |
| `capability 13` | `TUIDC_DFTCORRECTION` — absent |
| `capability 22` | `TUIDC_IMGMODESELECT` — absent |
| `capability 5` | `TUIDC_VERTICAL` — present, write does not take |
| `property 2` | `TUIDP_BRIGHTNESS` — absent |
| `property 3` | `TUIDP_BLACKLEVEL` — absent |
| `property 5` | `TUIDP_SHARPNESS` — absent |
| `property 7` | `TUIDP_HDR_KVALUE` — absent |

Capabilities 8, 10 and 15 (`ATLEVELS`, `HISTC`, `FLTCORRECTION`) should **not**
appear as errors — they are the readback-verified case above. If they start
appearing, the readback check has regressed.

## Reproducing this

The summary line is in every IOC log. For the per-id list, raise the driver's
trace mask to include `ASYN_TRACE_FLOW` (`0x10`) — the audit runs inside
`connectCamera()`, before `iocInit`, so it has to be set at config time rather
than through a PV:

```
# in st.cmd, third argument is the trace mask: 0x1 -> 0x11
axisSXR40Config("$(PORT)", $(CAMERA), 0x11, 0, 1610612736, 0, 0)
```

Then:

```bash
grep 'reportCapabilitySupport:' <iocLog>
```

Do this on a scratch copy of `st.cmd` rather than editing the real one — flow
tracing is very verbose during acquisition.

## If the camera is ever swapped

Every result here is **per-unit**. Re-run the audit, and re-check the
temperature calibration constants (`AXIS_TEMP_CAL_SLOPE` / `OFFSET` in
`axisSXR40.cpp`), which are this unit's factory values from the AXIS test report
for detector s/n 702 / board `KBSG09024003`.

## See also

- [known-gaps/README.md](../known-gaps/README.md) — what is unexercised or broken
- [TODO.md](../known-gaps/TODO.md) §3 — the `ReverseY` investigation
- [dhyana-xfxv4040bsi.md](dhyana-xfxv4040bsi.md) — full characterisation notes
- [porting/differences-from-adtucsen.md](../porting/differences-from-adtucsen.md) —
  divergence 4, where the audit was introduced
