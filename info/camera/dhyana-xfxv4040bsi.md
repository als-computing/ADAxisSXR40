# Tucsen Dhyana XFXV4040BSI — measured capabilities of this unit

> **This is the camera, not the detector.** The **AXIS-SXR-40** is the beamline
> instrument; the **Tucsen Dhyana XFXV4040BSI** (USB `5453:e41b`, s/n
> `KBSG09024003`) is the camera inside it, and everything here is camera-level.
> The SDK never reports the name "AXIS". Full breakdown of the three layers in
> [../README.md](../../README.md); note this is the **XFXV** variant (`E41B`), not
> the plain `Dhyana 4040BSI` (`E413`) — specs and firmware differ.

## At a glance — the numbers you'll keep needing

| | |
|---|---|
| Full frame | 4096 × 4096, 1 channel, 16-bit → **32 MiB per frame** |
| Binned modes | 2048×2048 (2×2), 1024×1024 (4×4) — via `TUIDC_RESOLUTION`, **not** the binning capabilities |
| Bit depth | fixed **16**, not adjustable |
| Exposure | **10.32 µs → 3600 s**, in 10.32 µs steps (one sensor row time) |
| Gain | `TUIDP_GLOBALGAIN` 0–5, integer steps |
| Measured throughput | **~289.5 MB/s** → **≈8.6 fps** at full frame |
| SDK frame ring | **2 frames** — ~230 ms of slack before drops |
| Sensor temperature | **−9.5 °C** measured; setpoint −20 °C; scale is offset (`raw = °C + 50`) |
| Dark frame at 50 ms | **mean ≈ 68 ADU**, max ~1000 (hot pixels) — exposure-dependent, see the sweep below |
| Frame buffer layout | pixels start at `pBuffer + 1024`; row stride `uiWidthStep` = 8192 |
| Not available | auto-exposure, test-pattern generator, HDR/CMS gain mode, rolling-scan control, exposure overlap |

---

## Is the camera connected? — four levels of confidence

Work down this list; each step proves more than the one before it. The first two
need no SDK at all.

### 1. Is it on the USB bus? (`lsusb`)

`lsusb` lists every device the kernel has enumerated. Filter by Tucsen's vendor
id so you don't have to read the whole thing:

```bash
lsusb -d 5453:
```

```
Bus 002 Device 012: ID 5453:e41b TUCSEN 16MP USB3.0 camera
    ^^^     ^^^        ^^^^ ^^^^
    bus     device     VID  PID
```

- **`5453`** is the vendor id — Tucsen. Always this.
- **`e41b`** is the product id — specifically the Dhyana **XFXV**4040BSI.
- **bus/device** numbers identify the device node, `/dev/bus/usb/002/012`. They
  **change on every replug**, so never hard-code them.

No output means the kernel cannot see the camera: check power and cable before
touching any software. You may also see
`2109:0813 VIA Labs VL813 Hub` — that is the USB3 hub inside the camera cable,
and it is expected.

`lsusb -v -d 5453:e41b` (add `sudo` for the full descriptor set) shows the
endpoints and confirms it is a **vendor-specific class** device with **no kernel
driver** — which is why access goes through libusb and why the udev rule matters.

### 2. Did it negotiate USB 3, and can you reach it?

`lsusb` says "connected" but not "connected *well*". Two things it doesn't tell
you, both of which break capture:

```bash
# Negotiated link speed. 5000/10000 = SuperSpeed. 480 = fell back to USB 2.
for d in /sys/bus/usb/devices/*/; do
  [ -f "$d/idVendor" ] && [ "$(cat $d/idVendor)" = 5453 ] &&
    echo "$(cat $d/product): $(cat $d/speed) Mbps"
done

# Can YOU write to the node? libTUCam needs write access, not just read.
ls -l /dev/bus/usb/002/012        # want crw-rw-rw-, not crw-rw-r--
```

A USB 2 fallback still *works*, which is what makes it dangerous: at 32 MiB per
frame you drop under 1 fps and `Buf_WaitForFrame` starts timing out, with nothing
obviously wrong. A non-writable node gives `uiCamCount == 0` from a perfectly
healthy camera.

### 3. Is the software installation sound?

```bash
./sdk/check.sh
```

Wraps both checks above and adds the SDK-side prerequisites (libraries,
`ldconfig` cache, `/etc/tucam/tuusb.conf`, this camera's PID in the allow-list,
udev rule). Exits non-zero on any failure.

### 4. Can the SDK actually talk to it and get pixels?

```bash
cd examples/CameraProbe && make && ./CameraProbe
```

The only test that proves the whole path. `cameras found: 1` means enumeration
works; at the default 50 ms a frame with `mean ≈ 68` means data is really
flowing — the figure scales with exposure, see the dark-frame
baseline below).

---

## About this document

Exhaustive sweep of every `TUIDC_*`, `TUIDP_*`, `TUIDV_*` and `TUIDI_*` id against
the actual camera on 2026-07-27. **This is what the unit really supports** — the
enums in `TUDefine.h` cover the whole Tucsen product line, and most ids in them
return an error here.

| Family | Supported | Total in enum | Section |
|---|---|---|---|
| Capabilities `TUIDC_*` | **18** | 73 | [below](#supported-capabilities--18-of-73-ids) |
| Properties `TUIDP_*` | **10** | 45 | [below](#supported-properties--10-of-45-ids) |
| Vendor properties `TUIDV_*` | **4** | 28 | [below](#supported-vendor-properties--4-of-28-ids) |
| Info ids `TUIDI_*` | 25 answer, **11 with real data** | 32 | [below](#info-ids) |

So roughly **three quarters of the API surface does not apply to this camera.**
Check `*_GetAttr` before building on any id — there is no "list what you support"
call, and looping ids is the only discovery mechanism.

Reproduce with `examples/CameraProbe` (which sweeps the interesting subset), or for a
full tally loop each family to its `*_END*` sentinel:

```c
for (INT32 id = 0; id < TUIDC_ENDCAPABILITY; ++id) {     // 0x49
    TUCAM_CAPA_ATTR a; memset(&a, 0, sizeof a); a.idCapa = id;
    if (TUCAMRET_SUCCESS == TUCAM_Capa_GetAttr(h, &a)) { /* supported */ }
}
// likewise TUIDP_ENDPROPERTY (0x2D), TUIDV_ENDVPROPERTY (0x1C), TUIDI_ENDINFO (0x21)
```

Device string as reported by the SDK's own startup log:
`Device:Dhyana XF/XV4040BSI, USB transfer rate:289.500, Blanking time:0x589`

> **These are measurements, not specifications.** Taken from serial
> `KBSG09024003` on 2026-07-27. Another unit, or a firmware update, may differ —
> re-run the sweep rather than trusting these tables if behaviour surprises you.

---

## Supported capabilities — 18 of 73 ids

| id | Name | cur | range | notes |
|---|---|---|---|---|
| `0x00` | `TUIDC_RESOLUTION` | 0 | 0..2 | **`0`=4096x4096, `1`=2048x2048(2x2Bin), `2`=1024x1024(4x4Bin)** |
| `0x01` | `TUIDC_PIXELCLOCK` | 0 | 0..0 | only `"High"` |
| `0x02` | `TUIDC_BITOFDEPTH` | 16 | 16..16 | fixed 16-bit, `step=0` |
| `0x04` | `TUIDC_HORIZONTAL` | 0 | 0..1 | horizontal mirror |
| `0x05` | `TUIDC_VERTICAL` | **1** | 0..1 | vertical flip, **on by default** |
| `0x07` | `TUIDC_FAN_GEAR` | 0 | 0..3 | `0`=High, `1`=Medium, `2`=Low, **`3`=Off (Water Cooling)** |
| `0x08` | `TUIDC_ATLEVELS` | 0 | 0..3 | `step=0` |
| `0x0A` | `TUIDC_HISTC` | 0 | 0..1 | histogram statistics, `step=0` |
| `0x0E` | `TUIDC_ENABLEDENOISE` | **1** | 0..1 | **on by default** — gates `TUIDP_NOISELEVEL` |
| `0x0F` | `TUIDC_FLTCORRECTION` | 0 | 0..3 | flat field: `0`=off, `1`=grab frame, `2`=calculate, `3`=correct |
| `0x13` | `TUIDC_VERCORRECTION` | 0 | 0..1 | |
| `0x17` | `TUIDC_CAM_MULTIPLE` | 1 | 1..4 | up to 4 cameras concurrently |
| `0x1D` | `TUIDC_ENABLEIMGPRO` | **14** | 0..255 | bitmask of enabled processing stages (`14` = `0b1110`) |
| `0x1E` | `TUIDC_ENABLELED` | 1 | 0..1 | front LED |
| `0x1F` | `TUIDC_ENABLETIMESTAMP` | 0 | 0..1 | `step=0` |
| `0x28` | `TUIDC_ENABLEPI` | 0 | 0..1 | |
| `0x31` | `TUIDC_ATLEVELGEAR` | 1 | 0..1 | |
| `0x3B` | `TUIDC_ENABLETEC` | **0** | 0..1 | see temperature note below |

### Notably NOT supported

`TUIDC_IMGMODESELECT` (CMS/HDR gain mode), `TUIDC_BINNING_SUM`/`_AVG`,
`TUIDC_ATEXPOSURE` (auto-exposure), `TUIDC_ROLLINGSCANMODE`/`_SLIT`/`_LTD`/`_DIR`,
`TUIDC_ENABLEOVERLAP`, `TUIDC_SHUTTER`, `TUIDC_CAMSTATE`, `TUIDC_HDR`,
`TUIDC_DFTCORRECTION` (defect correction — note `FLTCORRECTION` *is* supported),
`TUIDC_TESTIMGMODE` (no synthetic test pattern on this unit),
`TUIDC_ENABLEDSNU`, `TUIDC_PGAGAIN`.

Two consequences worth planning around:

- **Binning is done through `TUIDC_RESOLUTION`, not the binning capabilities.**
  Set resolution `1` or `2` before `Buf_Alloc`.
- **There is no auto-exposure and no test-pattern generator.** Exposure control is
  yours to implement; and you cannot validate the data path without light —
  use a dark frame's noise statistics instead (see below).

## Supported properties — 10 of 45 ids

| id | Name | cur | range | step | dft |
|---|---|---|---|---|---|
| `0x00` | `TUIDP_GLOBALGAIN` | 0 | 0 .. 5 | 1 | 0 |
| `0x01` | `TUIDP_EXPOSURETM` | 10.0001 | **0.01032 .. 3600060** ms | 0.01032 | 10.0001 |
| `0x04` | `TUIDP_TEMPERATURE` | **-9.52** | 0 .. 100 | 1 | 30 |
| `0x06` | `TUIDP_NOISELEVEL` | 3 | 0 .. 3 | 1 | 3 |
| `0x08` | `TUIDP_GAMMA` | 100 | 1 .. 255 | 1 | 100 |
| `0x09` | `TUIDP_CONTRAST` | 128 | 0 .. 255 | 1 | 128 |
| `0x0A` | `TUIDP_LFTLEVELS` | 0 | 0 .. 65534 | 1 | 0 |
| `0x0B` | `TUIDP_RGTLEVELS` | 65535 | 1 .. 65535 | 1 | 65535 |
| `0x2A` | `TUIDP_ATLEVEL_PERCENTAGE` | 10 | 0 .. 4990 | 10 | 10 |
| `0x2B` | `TUIDP_TEMPERATURE_TARGET` | 30 | 0 .. 100 | 1 | 30 |

**Exposure range is 10.32 µs to 3600 s (1 hour)** in 10.32 µs steps — the step is
one sensor row time. Requested values snap to that grid (asking for 50 ms yields
50.0004 ms).

`TUIDP_FRAME_RATE` and `TUIDP_BLACKLEVEL` are **not** supported; black level is
only reachable through the vendor properties below.

## Supported vendor properties — 4 of 28 ids

| id | Name | cur | range |
|---|---|---|---|
| `0x00` | `TUIDV_ADDR_FLASH` | 2 | 0 .. 4 |
| `0x17` | `TUIDV_BLACKLEVELHG` | 0 | 0 .. 65535 |
| `0x18` | `TUIDV_BLACKLEVELLG` | 0 | 0 .. 65535 |
| `0x19` | `TUIDV_HDR_KVALUE` | 800 | 1 .. 1024 |

These are factory/calibration values. Changing them affects image calibration —
leave them alone unless you know why you're touching them.

## Info ids

Of the 32 ids in `TUIDI_*`, **25 return success but only 11 carry real data** —
the rest answer `nValue = 0` with an empty string, which is indistinguishable
from a legitimate zero. Treat "call succeeded" as necessary but not sufficient;
the 11 that actually report something are:

| id | Name | value | interpretation |
|---|---|---|---|
| `0x01` | `TUIDI_BUS` | 768 = `0x300` | **USB 3.0** (`0x200` would be USB 2.0) |
| `0x02` | `TUIDI_VENDOR` | 21587 = `0x5453` | Tucsen |
| `0x03` | `TUIDI_PRODUCT` | 58395 = `0xE41B` | XFXV4040BSI |
| `0x0A` | `TUIDI_CURRENT_WIDTH` | 4096 | |
| `0x0B` | `TUIDI_CURRENT_HEIGHT` | 4096 | |
| `0x0C` | `TUIDI_CAMERA_CHANNELS` | 1 | monochrome |
| `0x19` | `TUIDI_TOTALBUFFRAMES` | 2 | host ring capacity |
| `0x1A` | `TUIDI_CURRENTBUFFRAMES` | 1 | **poll this for dropped-frame telemetry** |
| `0x1C` | `TUIDI_HDRKHVALUE` | 190 | |
| `0x1D` | `TUIDI_ZEROTEMPERATURE_VALUE` | **50** | raw temperature value corresponding to 0 °C |
| `0x1E` | `TUIDI_VALID_FRAMEBIT` | 16 | valid bits per pixel |

Three surprises:

1. **All text fields come back empty.** `TUIDI_CAMERA_MODEL`,
   `TUIDI_VERSION_API`, `TUIDI_VERSION_FRMW` return `nValue=0` and an empty
   string even with `pText`/`nTextSize` correctly set. The model name is only
   visible in the SDK's own stdout log line. Don't build logic on these — but
   note the **serial number is available** via `TUCAM_Reg_Read` with
   `TUREG_SN`, see the register-read note further down.
2. **`TUIDI_CURRENT_WIDTH`/`_HEIGHT` work via plain `TUCAM_Dev_GetInfo`, before
   `Buf_Alloc`** — contrary to the header comment ("must use
   `TUCAM_Dev_GetInfoEx` and after calling `TUCAM_Buf_Alloc`").
3. **Undocumented return code `0x80000312`** — returned by unsupported info ids
   (`0x06` FPGA ver, `0x07` driver ver, `0x11` working time, `0x12` fan speed,
   `0x1B` HDR ratio, `0x1F`). It is **not in the `TUCAMRET` enum** in
   `TUDefine.h`. Treat it as "id not supported by this model".
4. **`TUCAM_Buf_WaitForFrame` returns `TUCAMRET_ABORT` (`0x80000207`) after
   `Buf_AbortWait`**, not a timeout or success. This *is* in the enum, and it is
   the normal, expected outcome of a clean stop — so don't log it as an error.

`TUCAM_Dev_GetInfoEx(0, …)` supports a strict subset (`0x01`–`0x05`, `0x09`,
`0x0D`, `0x16`, `0x17`) — prefer the handle-based `TUCAM_Dev_GetInfo`.

## Temperature / TEC

The raw scale is offset by `TUIDI_ZEROTEMPERATURE_VALUE = 50`:

```
raw = °C + 50        →    raw 30 = -20 °C,  raw 50 = 0 °C,  raw 100 = +50 °C
```

So the property range `[0 .. 100]` is **-50 °C to +50 °C**, and the default
target of `30` means **-20 °C**.

Asymmetry to be aware of: **`TUIDP_TEMPERATURE` reads back the *actual sensor
temperature in real °C* (`-9.52`), but its documented range and its setter use
the raw offset scale.** Read it as °C; write it as raw. `TUIDP_TEMPERATURE_TARGET`
reads back raw (`30`).

Measured over 15 s, sensor temperature was stable at **-9.5 °C** while
`TUIDC_ENABLETEC` read **0**:

```
t= 0s  TUIDP_TEMPERATURE=  -9.516  TARGET=30  TUIDC_ENABLETEC=0
t=15s  TUIDP_TEMPERATURE=  -9.516  TARGET=30  TUIDC_ENABLETEC=0
```

A sensor holding -9.5 °C in a room-temperature lab means **the TEC is running**,
so `TUIDC_ENABLETEC`'s read-back of `0` does not reflect actual cooler state on
this model — don't use it to decide whether cooling is active; use the
temperature reading. The 10.5 °C gap from the -20 °C target is consistent with
the TEC being at its limit for the current ambient/airflow (fan gear is `High`).
**Unverified:** whether writing `TUIDC_ENABLETEC=1` changes anything, and whether
the gap closes with better cooling. Left untested to avoid changing thermal state
on a remote instrument.

`TUIDC_FAN_GEAR` option `3` is labelled **"Off (Water Cooling)"** — the unit
supports liquid cooling, and that setting is what disables the fan for it. Do not
select it on air cooling.

## Frame geometry, as reported

```
Buf_Alloc: 4096x4096  ucDepth=2  ucChannels=1  ucElemBytes=2
           uiImgSize=33554432  usHeader=1024  uiWidthStep=8192
```

- **`ucDepth` is `2`, not `16`.** Despite the header calling it "frame data
  depth", it carries *bytes* per pixel here. Get real bit depth from the
  `TUIDC_BITOFDEPTH` capability (16). Computing `(1 << ucDepth) - 1` for a
  max-value gives 3 and silently ruins any image export.
- `usHeader = 1024` — **1024 bytes of metadata precede the pixels**; pixel data
  starts at `pBuffer + 1024`.
- `uiWidthStep = 8192` = 4096 × 2 exactly, so no row padding at full frame. Still
  use `uiWidthStep` rather than assuming it.
- `uiImgSize = 33554432` = **32 MiB per frame**.
- **`uiIndex` stayed `0` across all frames** — it is not a working frame counter
  on this unit. Count frames yourself, and use `TUIDI_CURRENTBUFFRAMES` to detect
  backlog.

`TUIDI_TOTALBUFFRAMES = 2` means the SDK's internal ring is only 2 frames deep at
full resolution; the driver log confirms `[BeginBulkInDataTransfer]: Can get 2
frames!`. **Your consumer must keep up within ~2 frame times or you drop frames.**
At the measured 289.5 MB/s that's roughly 8.6 fps and ~230 ms of slack.

## Dark-frame baseline (lens capped / dark room, gain 0)

At 50 ms:

```
frame 0: min=11  max=1103  mean=68.1
frame 1: min=0   max=1038  mean=68.1
frame 2: min=10  max=1049  mean=68.1
```

Max ~1000 ADU is hot-pixel outliers, expected for a BSI sCMOS at -9.5 °C.

### The mean depends on exposure — one number is not a pass/fail test

Measured sweep, three frames per point, same optical conditions (the 50 ms point
reproduces the run above to within 0.1 ADU):

| Exposure | Mean (ADU) | | Exposure | Mean (ADU) |
|---|---|---|---|---|
| 5 ms | 57.7 | | 100 ms | 69.9 |
| 10 ms | 58.9 | | 200 ms | 73.6 |
| 20 ms | 61.7 | | 400 ms | 80.9 |
| 50 ms | 68.2 | | | |

So **≈68 ADU is the baseline *at 50 ms*, not a universal constant.** Someone
checking health at 10 ms sees 59 and someone at 400 ms sees 81; neither is a
fault. Compare against the same exposure you measured at, or re-measure this
curve for your own operating point.

What *is* stable and worth testing against:

- **Frame-to-frame repeatability at a fixed exposure: ±0.1 ADU.** Every pair in
  the sweep agreed to within 0.1. A mean that moves between consecutive frames
  at constant exposure is a real problem — that part of the original advice holds.
- **Long-term stability at a fixed exposure.** 50 ms gave 68.3 and, 1.5 hours of
  continuous use later, 68.15.
- **All-zero output** is always wrong.

Note the curve is not a straight line: roughly 0.22 ADU/ms below 50 ms but only
0.036 ADU/ms above 100 ms, a ~6× change in slope. Pure dark current would be
linear, so something else contributes at short exposures. Don't extrapolate
between the measured points; if you need an accurate dark reference, take it at
your actual exposure.

**On-camera processing is ruled out as the cause.** `TUIDC_ENABLEDENOISE` reads
`1` and `TUIDC_ENABLEIMGPRO` reads `14` on this unit, which made image processing
the obvious suspect. It is not: fetching the *same frame* both ways gives
**bit-identical data**.

| Exposure | `TUFRM_FMT_USUAl` mean | `TUFRM_FMT_RAW` mean | Δ |
|---|---|---|---|
| 5 ms | 59.22 | 59.22 | 0.00 |
| 20 ms | 63.08 | 63.08 | 0.00 |
| 50 ms | 69.75 | 69.75 | 0.00 |
| 100 ms | 71.50 | 71.50 | 0.00 |
| 200 ms | 75.10 | 75.10 | 0.00 |
| 400 ms | 82.68 | 82.68 | 0.00 |

min and max matched exactly too. Two consequences:

- **`TUFRM_FMT_USUAl` is safe for quantitative work on this camera.** The
  processing capabilities read as enabled but do not alter 16-bit mono output, so
  there is no need to chase `TUFRM_FMT_RAW` for unfiltered data. (Add this to the
  list of capability read-backs on this model that don't reflect reality —
  `TUIDC_ENABLETEC` reads `0` while the cooler is plainly running.)
- The non-linear dark curve remains **unexplained**. It is not denoise.

The technique is worth knowing independently: **`TUCAM_Buf_CopyFrame` re-fetches
the frame you are already holding in a different `ucFormatGet`**, so you can have
both processed and raw views of the *same* photons rather than two different
frames. The vendor GUI uses it exactly this way to write a RAW file alongside a
processed one (`examples/QtDemo/waittingthread.cpp:237`).

## The auto-generated profile file — and the serial number

On first successful open, the SDK writes a profile into whatever directory you
passed as `TUCAM_INIT.pstrConfigPath`:

```
Dhyana XFXV4040BSI_PIDe41b_KBSG09024003.xml
^^^^^^^^^^^^^^^^^^        ^^^^  ^^^^^^^^^^^
model                     PID   SERIAL NUMBER
```

Serial of this unit: **`KBSG09024003`**.

> **Correction.** This document previously said the filename was the *only* place
> the serial is exposed. That is wrong. Every `TUIDI_*` **text** field does come
> back empty, but the serial is readable through the register interface:
>
> ```c
> char sn[TUSN_SIZE] = {0};
> TUCAM_REG_RW rw; memset(&rw, 0, sizeof rw);
> rw.nRegType = TUREG_SN; rw.pBuf = sn; rw.nBufSize = TUSN_SIZE;
> TUCAM_Reg_Read(h, rw);              // -> "KBSG09024003"
> ```
>
> Verified by `examples/ControlProbe`. Prefer this over parsing the filename —
> it needs no prior successful open and no assumptions about `pstrConfigPath`.
> (It is also how ADTucsen populates `ADSerialNumber`.)

Two practical consequences:

- `pstrConfigPath` must point at a **writable, stable** directory. `examples/CameraProbe`
  uses `"./"`, so the XML lands in the working directory; a real application
  should use a fixed config dir so the camera's saved state persists across runs.
  The `LoadCameraProfiles` warning on a fresh install is just this file not
  existing yet.
- Contents are a `<ParameterSets>` snapshot managed by
  `TUCAM_File_SaveProfiles` / `TUCAM_File_LoadProfiles`:

```xml
<Cam_DhyanaXFXV4040BSI Using="DftParameter">
  <ParameterSets Name="DftParameter">
    <Resolution>0</Resolution>          <BitOfDepth>16</BitOfDepth>
    <GlobalGain>0</GlobalGain>          <LNExposure>4845</LNExposure>
    <BlackLevel>100</BlackLevel>        <Temperature>30</Temperature>
    <FanMode>0</FanMode>                <TECEnable>0</TECEnable>
    <ImageProcessEnable>14</ImageProcessEnable>
    ...
```

Note `LNExposure=4845` — exposure is stored internally as a **line count**, which
is why the property's step is one row time (10.32 µs). 4845 × 10.32 µs ≈ 50 ms,
the value that had been set.

Careful reading this file for capability discovery: it lists `<ImageModeSelect>`,
`<TestImageMode>`, `<FrameRate>` and `<SensorReset>` even though the
corresponding `TUIDC_*`/`TUIDP_*` ids return errors on this camera, and its
`<Horizontal>1</Horizontal>` disagrees with the live read of `0`. **It is a
default-parameter template for the model family, not a description of live
state.** Trust `*_GetAttr` / `*_GetValue`, not this XML.

## Control path — all verified working

`CameraProbe` only reads and captures. `examples/ControlProbe` exercises the
*write* side, which matters because **an unsupported `Set` in this SDK returns
`TUCAMRET_SUCCESS` and silently does nothing** — so every result below is
confirmed by reading the value back, not by trusting the return code.

| Call | Result on this unit |
|---|---|
| `Reg_Read(TUREG_SN)` | `"KBSG09024003"` — the serial, properly |
| `Capa_SetValue(TUIDC_RESOLUTION)` | mode 0→1 works; `Buf_Alloc` then reports 2048×2048, step 4096 |
| `Cap_SetROI` | 2048×2048 centred ROI accepted exactly as requested |
| `Cap_GetTrigger` | `mode=0 exp=0 edge=1 delay=0 frames=1 **bufFrames=2**` |
| `Cap_SetTrigger` | verified by readback |
| `Cap_GetTriggerOut` | **3 ports**, all `mode=5 edge=0 delay=0 width=5000` |
| `Cap_SetTriggerOut` | verified by readback on all 3 ports |
| `Cap_DoSoftwareTrigger` | fires and delivers a 4096×4096 frame |
| `Buf_AbortWait` | unblocks a waiting `WaitForFrame` in ~0 ms |

Three things worth pulling out:

- **Binned and ROI frames are unpadded.** `uiWidthStep` came back as exactly
  `width × 2` in every mode tested (8192 at 4096², 4096 at 2048²). Row-stride
  handling is still the correct way to write a copy loop, but no padding was
  observed on this camera.
- **`nBufFrames = 2` in the trigger attributes** independently confirms the
  2-frame host ring seen in the SDK's `"Can get 2 frames!"` startup line.
- **Three trigger-out ports exist**, so trigger-out is genuinely available here —
  worth knowing since ADTucsen disables the whole feature if any port probe fails.

Nothing in that table left the camera reconfigured; every mutating test restores
the prior value and re-reads it to confirm.

## Harmless startup noise

The SDK writes these to stdout on every run. All benign:

```
[PhxCoreOpen]:handle = 1, dwBoardNumber = 1        ← probing for ActiveSilicon
[OpenPhxCore]:Failed to open channel.                 frame grabbers; none fitted
[BeginBulkInDataTransfer]:Can get 2 frames!        ← ring depth, informational
[WARNING] TUCamBase.cpp LoadCameraProfiles(3538):  ← no saved profile yet;
  There is not parameter sets inforamtion...          created on first save
[PerformDataXfer]:Finished thread!                 ← clean thread teardown
```

There is no API to silence them; redirect stdout if it pollutes your logs.
