# Stop deadlock — `TUCAM_Cap_Stop` hangs under the asyn port lock

Found **2026-08-25** on `bl1101ad01` (KVM guest, camera `KBSG09024003`, SDK
2.0.7.0), while running the ROI frame-rate sweep. Caught live with `gdb` twice — in
**three shapes with one cause** (see "Second shape" and "cause, or only the victim") — and the stacks are below. **This is the single root cause behind three things that had
each looked like a separate problem**: the "ROI latches at 32 rows", the IOC
refusing to `exit`, and the camera needing a reset after every IOC kill.

## What an operator sees

After `Acquire` is set to 0 following acquisition at a small ROI height
(observed at 128, 32 and 8 rows), the IOC goes quietly dead from the driver's point
of view while looking alive from everywhere else:

| Observation | Value | Why it misleads |
|---|---|---|
| `DetectorState_RBV` | `Acquire` (this driver) / `Idle` (upstream) | camera is *not* streaming — `ArrayCounter_RBV` is static, `ArrayRate_RBV` 0. Not a reliable indicator on either driver; see "Confirmed on upstream" below |
| `StatusMessage_RBV` | `Acquiring...` | stale; never updated |
| `SizeY` write | readback never changes | reads as "camera refuses the ROI" — the write was never processed |
| `HDF1:ArrayCounter_RBV` | 0 | reads as a file-plugin fault — no plugin gets frames because the driver is stuck |
| `caget` of anything | works | `I/O Intr` records serve their last value from the database |
| `caput` to `cam1:*` | returns, no alarm | request queues on the asyn port and sits there (`nQueued 8`) |
| `exit` in iocsh | hangs | shutdown needs the same port lock |
| `SIGTERM` | ignored | same |
| `SIGKILL` | works; camera then unclaimable | 3 of 3 — but in each case the camera had **already stopped answering** (that is what hung the SDK), so the kill is probably not what wedges it |

Every line in the "Why" column was, at some point in the last two days, taken at
face value and chased as its own bug.

## Mechanism

Three threads, one lock. `asynReport 3 AXISSXR40` at the time:
`synchronousLock:Yes  nQueued 8  blocked:No`.

**1. The asyn port thread holds the port lock and never returns.**
`writeInt32(ADAcquire = 0)` → `stopCapture()` → `TUCAM_Cap_Stop` →
`CTUCamBase::StopCapture` → `CTUDrvCypress::FinishBulkInDataTransfer` → a libc
wait (join / condvar). Because `writeInt32` runs inside the port thread under
`synchronousLock`, **the lock is held for as long as the SDK blocks — which is
forever.**

**2. The SDK's transfer thread is blocked in a synchronous USB read with no
timeout.** `CTUDrvCypress::perform_data_xfer` →
`cyusb_sync_transfer_wait_for_completion` → `libusb_handle_events_completed` →
`poll()`. It is waiting for the next bulk-in packet. Capture has been stopped,
so that packet is never coming. `FinishBulkInDataTransfer` is waiting for this
thread to finish. It won't.

**3. Everything else in the driver queues behind the port lock.** The image task
(`grabImage`, line 844, re-taking the lock after `WaitForFrame` returned) and the
temperature task (line 1472) are both in `asynPortDriver::lock()`. Every
subsequent `caput` to the driver joins the asyn queue and stays there.

The SDK hang is Tucsen's bug — a stop path that joins a thread which can be
parked in an untimed synchronous transfer. **Holding the asyn port lock across
that call is ours**, and it is what turns a stuck SDK into a dead IOC.

## Stacks

`gdb -p <ioc> -batch -ex 'thread apply all bt'`, 2026-08-25 11:1x, trimmed to
the four threads that matter. Full 133-thread dump, IOC log and sweep log are in
`~/axis-deadlock-evidence/` on `bl1101ad01`.

```
Thread 130 "AXISSXR40"  -- the asyn port thread, HOLDING the port lock
#0-3  libc wait
#4  CTUDrvCypress::FinishBulkInDataTransfer()        libTUCam.so.1
#5  CTUCamBase::StopCapture()                        libTUCam.so.1
#6  TUCAM_Cap_Stop(_tagTUCAM*)                       libTUCam.so.1
#7  axisSXR40::stopCapture                           axisSXR40.cpp:1932
#8  axisSXR40::writeInt32 (value=0)                  axisSXR40.cpp:1137
#9  asynPortDriver writeInt32                        asynPortDriver.cpp:2004
#10 processCallbackOutput                            devAsynInt32.c:510
#11 portThread                                       asynManager.c:920

Thread 2 "AxisSXR40ImageR"  -- SDK-internal transfer thread (inherited name)
#3  poll()
#4  handle_events                                    libTUCam.so.1
#5  libusb_handle_events_timeout_completed           libTUCam.so.1
#6  libusb_handle_events_completed                   libTUCam.so.1
#7  cyusb_sync_transfer_wait_for_completion(...)     libTUCam.so.1
#8  CTUDrvCypress::perform_data_xfer(void*)          libTUCam.so.1

Thread 126 "AxisSXR40ImageR"  -- the driver's image task, WAITING for the lock
#2  mutexLock (id=0x561f0a234c20)                    osdMutex.c:117
#3  epicsMutexLock (pmutex=0x561f0a234c00)           osdMutex.c:164
#4  asynPortDriver::lock                             asynPortDriver.cpp:949
#5  axisSXR40::grabImage                             axisSXR40.cpp:844
#6  axisSXR40::imageGrabTask                         axisSXR40.cpp:743

Thread 125 "AxisSXR40TempRe"  -- temperature task, WAITING for the same lock
#3  epicsMutexLock (pmutex=0x561f0a234c00)           osdMutex.c:164
#4  asynPortDriver::lock                             asynPortDriver.cpp:949
#5  axisSXR40::tempTask                              axisSXR40.cpp:1472
```

Same mutex (`0x561f0a234c00`) in threads 126 and 125; same owner (thread 130).

## When it happens

Every observation is a `stopCapture()` after continuous acquisition. Tally so
far, by the ROI height that was being acquired when `Acquire=0` was written:

| Height | Stops observed | Deadlocked |
|---|---|---|
| 4096 … 256 (5 heights) | 20 | **0** |
| 128 | 3 | **1** |
| 64 | 2 | 0 |
| 32 | 2 | **2** |
| 8 | 2 | 1 |
| **32, temperature poll disabled** (`AXIS_NO_TEMP_POLL=1`) | 1 | **1** |
| **upstream ADTucsen IOC, 32** | 1 | **1** |

Frame rate at the time: 128 rows ≈ 240 fps, 32 rows ≈ 860 fps, 8 rows ≈ 1500 fps.
So it is rate-dependent and probabilistic. The 128-row event (13:25, the third stop
at that height after two clean ones) removed any idea of a safe threshold: it has not
been seen in 20 stops at ≥ 256 rows (≤ 128 fps), which is not proof it cannot happen
there.

**Confirmed on upstream ADTucsen — 2026-08-25 11:48.** The same script, same
mode and same heights were run against Damon's unmodified ADTucsen IOC (`XV4040:`,
`tucsen.cpp`, same SDK). Its **first** stop at 32 rows — after acquiring at 860.5 fps,
the same rate as this driver — deadlocked it: `asynReport 3 TUCSEN` gave
`synchronousLock:Yes nQueued 8`, `ArrayCounter_RBV` froze, four further `Acquire=1`
writes produced 0 frames, five `SizeY` writes never took, and a write to
`AcquireTime` never reached the driver. Log: `~/axis-perf-results/adtucsen-control-*.log`.

So this is the SDK's stop path, triggered identically by both drivers. The ways
ADAxisSXR40 differs from upstream — zero-initialised handles, the explicit
`WaitForFrame` timeout, the row copy — are irrelevant to it, and the fix below
applies to both. **Damon needs to know.**

One presentational difference matters for detection: on upstream,
`DetectorState_RBV` read **`Idle`** while deadlocked, not `Acquire`. Upstream's
image task sees `ADAcquire=0`, marks Idle and releases the lock *before* the port
thread's `Cap_Stop` hangs (both threads call `Cap_Stop`; upstream's image task also
calls it, unlocked, in its idle branch). So `DetectorState` is **not a reliable
indicator on either driver**. The reliable test is a write that must round-trip —
`roi-rate-test.sh` now resets `ArrayCounter` after every stop and requires the
readback to follow.

## Second shape — the temperature task (2026-08-25 13:25)

The write sweep's stop after acquiring at **128 rows** (~240 fps — a height that had
survived two earlier stops) deadlocked the IOC again, and `gdb` showed a **different
thread holding the lock**. `asynReport 3 AXISSXR40`: `synchronousLock:Yes nQueued 1`.

```
Thread 124 "AxisSXR40TempRe"  -- temperature task, HOLDING the port lock
#3  poll()
#4  handle_events                                    libTUCam.so.1
#5  libusb_handle_events_timeout_completed           libTUCam.so.1
#6  libusb_handle_events_completed                   libTUCam.so.1
#7  sync_transfer_wait_for_completion                libTUCam.so.1
#8  libusb_control_transfer                          libTUCam.so.1
#9  CTUDrvCypress::CommitURB(_tagURB&)               libTUCam.so.1
    ... TUCAM_Prop_GetValue / TUCAM_Dev_GetInfo from tempTask, called under lock()

Thread 129 "AXISSXR40"  -- the asyn port thread, WAITING for the lock
#4  asynPortDriver::lock                             asynPortDriver.cpp:949
#5  writeInt32 (value=0)                             asynPortDriver.cpp:2003
#6  processCallbackOutput                            devAsynInt32.c:510
#7  portThread                                       asynManager.c:920

Thread "AxisSXR40ImageR"  -- image task, IDLE: the stop had completed normally
#4  epicsEventWait                                   osdEvent.c:104
#5  axisSXR40::imageGrabTask                         axisSXR40.cpp:693
```

Full dump: `~/axis-deadlock-evidence/gdb-all-threads-2026-08-25-1325-h128.txt`.

Here `TUCAM_Cap_Stop` **returned**. The image task finished the stop and parked in
its idle wait; `DetectorState_RBV` read `Idle`. Then the temperature task — which in
both drivers runs `lock(); while(...) { TUCAM_Prop_GetValue(); TUCAM_Dev_GetInfo(); ...;
unlock(); sleep(0.5); lock(); }` — issued its next USB **control** transfer to read
the sensor temperature, and that transfer never completed. Lock held forever; the
port thread queued behind it on the very next write.

What the two shapes have in common is the real root cause:

> **After a stop at high frame rate, the camera stops completing USB transfers —
> bulk (shape 1) and control (shape 2) alike. Whichever SDK call is then in flight
> blocks forever, because every `TUCAM_*` call ends in a synchronous libusb transfer
> with no timeout. And because both drivers make SDK calls while holding the asyn
> port lock — in `writeInt32` and in a 0.5 s temperature poll — a silent camera
> becomes a dead IOC within half a second, even when `Cap_Stop` itself returns.**

Three consequences:

- **`DetectorState_RBV` is useless as an indicator on either driver** — it read
  `Idle` here on this driver too. Only a write round-trip proves the port thread is
  alive; `roi-rate-test.sh` now does exactly that after every stop.
- **The fix must cover every SDK call made under the lock**, not just `Cap_Stop`.
  The temperature poll is the most dangerous because it runs unconditionally every
  0.5 s. See Fix.
- **The camera goes silent *before* any kill.** In all three "SIGKILL wedged the
  camera" cases the IOC was already deadlocked — i.e. the camera had already stopped
  answering. The kill is probably incidental. A USB device that stops completing
  control transfers after a bulk stream ends is a USB-path pathology, which is
  exactly what the VM/controller hypothesis above predicts and what the physical
  host never showed in 18 stops.

### Open question — is the poll a cause, or only the victim?

Calling the temperature poll a "trigger" overstates the evidence. In shape 1 the
poll was *waiting for the lock*, not inside the SDK, when `Cap_Stop` hung on its own
bulk read — so it cannot have caused that one. What the evidence supports is that it
is the most frequent **victim**: the SDK call most often in flight when the camera
goes silent.

There is, however, a live hypothesis it *does* contribute to the cause: USB control
transfers (the poll's `Prop_GetValue` / `Dev_GetInfo`, every 0.5 s — four per cycle
in this driver, two in upstream) interleaved with a bulk stream stop might be what
upsets the camera or the passed-through controller. Nothing so far excludes it.

**Test:** the driver now honours `AXIS_NO_TEMP_POLL` (any value, in the IOC's
environment) and skips the poll thread entirely, logging a loud `DISABLED` line at
start. Run `~/axis-perf-results/stop-test.sh 32 10` against an IOC started that way.

| Outcome | Meaning |
|---|---|
| deadlocks anyway (in `Cap_Stop`, shape 1) | poll is innocent as a cause — it was only the fastest victim; the fix stays "no SDK call under the lock" |
| 10 stops survive where 2 of 2 previously failed | the poll's control transfers are part of what silences the camera — a second, cheaper mitigation exists (lower the poll rate, or pause it around stops), and Tucsen gets a sharper report |

**Result — 2026-08-25 13:49: the poll is a victim, not a cause.** IOC started with
`AXIS_NO_TEMP_POLL=1` (verified: `DISABLED` in the log, no `TempRe` thread, readback
frozen). The first stop at 32 rows (862 fps) went through — and the camera went
silent anyway. The very next SDK call under the port lock was the **exposure write**
at the start of the following point, and it hung. Third shape, same cause:

```
Thread 128 "AXISSXR40"  -- port thread, HOLDING the lock
#7  sync_transfer_wait_for_completion                libTUCam.so.1
#8  libusb_control_transfer                          libTUCam.so.1
#9  CTUDrvCypress::CommitURB(_tagURB&)               libTUCam.so.1
#10 CTUReqMgrBase::SubmitRequests(CTUDrvBase*)       libTUCam.so.1
#11 CTUCamBase::SetPropertyValue(int, double, uint)  libTUCam.so.1
#12 axisSXR40::setProperty (property=1 TUIDP_EXPOSURETM, value=0.02)
#13 axisSXR40::writeFloat64 (AcquireTime = 2e-05)
#15 processCallbackOutput                            devAsynFloat64.c:336
#16 portThread                                       asynManager.c:920
```

`asynReport`: `synchronousLock:Yes nQueued 8` — the eight remaining writes of that
point. Full dump: `~/axis-deadlock-evidence/gdb-portthread-deep-2026-08-25-1350-notemp.txt`.
`exit` hung as before. So: remove the poll and the next `TUCAM_*` call becomes the
victim — every SDK call under the lock is exposed, exactly as Fix 1 says. Removing
or slowing the poll is **not** a mitigation. (n = 1, but the direction is unambiguous:
the camera stopped answering before any poll could have run.)

A bug this run exposed in the test itself: the liveness check skipped its write
round-trip when `ArrayCounter` was already 0 — and passed nine times in a row on a
deadlocked IOC, because nothing was acquiring so the counter stayed 0, while
`SizeY_RBV` was stale-true and `DetectorState` stale-`Idle`. The probe now always
writes a value that differs from the readback, and a point that acquires zero frames
exits 4 and stops the run. `AXIS_NO_TEMP_POLL` remains diagnostic only: with it set,
`TemperatureActual`, `TransferRate`, `BuffFrames` and `BuffTotal` stop updating.

**Where gdb stops being useful.** Three dumps now all end the same way: inside
`libTUCam`, in `libusb`, in `poll()`, waiting for a USB completion that never comes.
gdb has located *where the software waits*; it cannot see *why the transfer never
completes* — that is below the SDK, in the controller/hypervisor/camera path. The
next tool is a `usbmon` capture around a 32-row stop (root; see
`~/axis-perf-results/usbmon-capture.sh` — this kernel runs Secure Boot lockdown
`integrity`, so the debugfs text interface returns `EPERM` even to root and the helper
reads the binary `/dev/usbmonN` device instead): if the URB is submitted and never
completed, the passed-through controller or the device is not returning it; if it
completes with an error status the SDK is ignoring, that is Tucsen's. Either way it
is the first evidence from below the SDK — and it should be repeated on `psc-razer`.

## Why it was misdiagnosed for two days

The first visible symptom is always downstream of the real fault:

- **"ROI latches at 32."** `SizeY_RBV` stops following `SizeY`. Two power/reboot
  cycles were spent on the theory that the camera firmware locked its ROI. It
  never did — the `SetROI` call simply never ran.
- **"HDF5 writes 0 frames."** The plugin logged
  `NDPluginFile::doCapture: ERROR, must collect an array to get dimensions first`
  — true, and irrelevant: the driver had stopped delivering arrays to anyone.
- **"The IOC won't exit / SIGTERM is ignored."** Filed as a missing
  `epicsAtExit` handler. Partly right — but the immediate cause of *this* hang is
  the port lock being held by a stuck SDK call. Notably, `exit` **works** when the
  camera failed to connect, which is consistent: no `Cap_Stop` was ever issued.
- **`caput -c` returning cleanly.** The asyn queue accepts the request; nothing
  ever dequeues it. No alarm is raised.

The test script's own pre-flight made it worse: its "prime" step polled
`ArraySizeY_RBV == H`, which was *already* true from the stale readback, so the
prime "passed" without a frame ever being produced. Fixed — see
[performance/README.md](../performance/README.md).

## Recovery

| Step | Result |
|---|---|
| `exit` / `SIGTERM` | no effect (lock held) |
| `SIGKILL` the IOC | IOC gone; camera enumerates but descriptor reads time out and `TUCAM_Dev_Open` fails with `[OpenDevice]:Error in claiming interface!` (`0x80000110`). 3 of 3 — but the camera had already stopped answering before each kill (see "Second shape"). |
| USB device `unbind`/`bind` (root; the path was `10-2.2` on that boot — **it changes across reboots**, see note below the table) | descriptors readable again; interface **still** cannot be claimed. 1 of 1. |
| xhci controller `unbind`/`bind` of `0000:01:00.0` (root) | enumerates and answers descriptor reads again — **but the next IOC start hangs inside the camera open** (`tucsenConfig`, 9 threads, never reaches `iocInit`) and the device stops answering. **Not a recovery.** 1 of 1 (2026-08-25 11:33). |
| **Reboot the VM** | **full recovery**, 6 of 6 today. No detector power cycle needed — the reboot re-initialises the passed-through xhci controller. |
| Detector power cycle | not required for this fault (it was done once on 2026-08-24 for a different one) |

**The camera's bus number is not stable across reboots on this VM.** It was
`Bus 010` on one boot and `Bus 003` on the next — probe order among one
passed-through ASMedia controller and nine virtual QEMU ones. libusb finds the
camera by vendor/product id, so neither SDK cares, and it is **not** connected to
the deadlock (which reproduces within a single boot). But any recovery or udev
rule written against a bus path (`/dev/bus/usb/010/003`, `10-2.2`) will silently
target nothing after a reboot. Locate it by id every time:
`lsusb -d 5453:e41b` or `grep -l 5453 /sys/bus/usb/devices/*/idVendor`.

## Does the VM make it worse? Probably — and that is testable

The race is in the SDK, but **how often it is lost looks environment-dependent**:

| | Stops at 32 / 8 rows | Deadlocked |
|---|---|---|
| Physical host, 2026-07-29 sweep (Intel i7, on-board xHCI, bare metal) | ≥ 4 (both modes completed at both heights; 18 stops in the whole sweep) | **0** |
| This VM, 2026-08-25 morning (**ASMedia ASM2142** via VFIO passthrough, KVM) | 5, across two drivers | **4** |
| This VM, 2026-08-25 16:31–16:40 (**Renesas uPD720202** via VFIO passthrough, same hub, same camera) | **38** (10 at 32 rows, the full 9-height sweep both modes, 10 at 8 rows at 3567 fps) | **0** |

Same script, same camera, same SDK binary (md5-identical `libTUCam.so.1.0.0`).

The mechanism is consistent with that. `FinishBulkInDataTransfer` joins a thread
in a synchronous bulk read; whether the read completes before the join is a race
against USB completion latency. That latency is measurably worse here — the same
sweep shows the VM losing 5 % at 8 fps but 57 % at 1500 fps, i.e. a large
**per-completion** cost crossing the hypervisor — and the deadlock only appears
above ~800 fps, where the frame period is ~1 ms. A window that is microseconds on
bare metal is plausibly a millisecond here.

Three things are confounded inside "the VM" and cannot be separated from this
host: VFIO interrupt-delivery latency, the ASM2142 controller (the physical host
used a different one), and the kernel (6.12 vs 7.0). The post-kill behaviour points
the same way — neither a device rebind nor an xHCI controller rebind recovers the
camera, only a guest reboot, which is the one event that gives the passed-through
controller a full PCI reset; and after a detector power cycle on 2026-08-24 the
camera and its hub did not re-enumerate until a reboot either. That is the
controller (or VFIO) misbehaving, not the camera and not either driver.

**None of this changes the fix.** An untimed join on an untimed read is wrong on
any host, and holding the asyn port lock across it is wrong on any host. It does
change the priority of two conversations: with Tucsen (include the VM/bare-metal
contrast — it will help them reproduce), and with whoever runs Proxmox (interrupt
remapping / MSI settings for the VFIO device, a different controller, or a
bare-metal host for this detector).

**The decisive experiment:** run `adtucsen-stop-control.sh`-style stops — ten at 32
rows — on `psc-razer`, bare metal, with the same script. Survives → the VM is the
amplifier. Deadlocks → purely the SDK. Needs the detector's USB moved, so it is a
next-visit item.

## Below the SDK — what `usbmon` saw (2026-08-25 14:42)

One deadlock captured end to end with the kernel's binary USB monitor
(`/dev/usbmon10`, kernel ring **dropped = 0**, so nothing is missing). Normal
configuration, poll on. Same session: gdb showed shape 2 — `Cap_Stop` returned, image
task idle, temperature poll's control read holding the lock. Excerpt:
`~/axis-deadlock-evidence/usbmon-excerpt-stop-and-hang-1442.txt`; full capture
beside it. Times are the capture's seconds.

| t | event | meaning |
|---|---|---|
| … → 4142.7759 | `C Bi:10:3:1 st=0 len=262152` every ~1.16 ms, next `S Bi` always queued | healthy 860 fps stream, right up to the stop |
| 4142.7765 | 29 × `C Bi:10:3:1 st=-2 len=0` (two partial: 232448 B, 23552 B) | `Cap_Stop` **cancels** its queued bulk URBs (−2 = ENOENT, unlinked by the host) |
| 4142.84 → 4144.30 | 15 cancelled completions arriving **104.0 ms apart, regular to 0.1 ms** (101.0 then 104.0 × 13), 1.45 s in all | each URB unlink takes ~100 ms to complete — xHCI should do this in milliseconds, and a period that exact is a timer firing, not queueing jitter |
| **never** | *no* `Co:10:3:0` (control-OUT) anywhere near the stop — all 8 commands in the capture are at 4134.5–4134.9, point setup | **`Cap_Stop` sends the camera no stop command.** It only stops the host from reading. |
| **4144.2971** | `S Ci:10:3:0 len=4` — the temperature read, 0.35 ms after the last cancel | submitted and **never completed**: no `C`, no error, no cancel. This is the transfer gdb shows the port thread waiting on. |

Three facts and one strong hint:

1. **The SDK's stop does not tell the camera to stop.** It cancels the host's bulk
   reads and leaves the camera streaming into a pipe nobody drains. Whatever the
   camera's FX3 firmware does when its bulk FIFO backs up is what happens next.
2. **After that, the device's control endpoint goes dead.** The very next EP0 transfer
   is never returned — consistent with the earlier observation that even `lsusb -v`
   descriptor reads time out afterwards. So the *camera* (or the controller's
   endpoint context for it) stops servicing EP0, and only a reboot's PCI reset of the
   passed-through controller brings it back.
3. **The hang is not a lost or errored completion the SDK ignored.** It is a genuinely
   outstanding URB. Tucsen's untimed synchronous transfer then blocks forever, and
   the driver's lock turns that into a dead IOC.
4. **The 100 ms-per-cancel ladder is the passthrough fingerprint.** URB unlink on xHCI
   is a Stop-Endpoint command plus an interrupt; ~100 ms each is what delayed
   interrupt/command completion through VFIO looks like, and it stretches the stop
   from a few ms to 1.5 s — a window in which the un-stopped camera keeps pushing
   into a pipe that is being torn down. That is a plausible reason the same SDK stop
   is harmless on bare metal (18 of 18) and fatal here (5 of 7 at ≤32 rows).

### And what the kernel's xHCI driver logged at the same instant

`sudo dmesg -T | grep -iE 'xhci|usb 10-'` (saved as
`~/axis-deadlock-evidence/dmesg-xhci-1442.txt`). Controller: ASMedia `0000:01:00.0`,
`hci version 0x110`, `quirks 0x0000000000800010`. Camera at `usb 10-2.2`, behind the
VIA VL813 hub at `10-2`.

```
[14:42:22] xhci_hcd 0000:01:00.0: ERROR Transfer event TRB DMA ptr not part of current TD ep_index 2 comp_code 28
[14:42:22] xhci_hcd 0000:01:00.0: ERROR Transfer event TRB DMA ptr not part of current TD ep_index 2 comp_code 28
[14:42:22] xhci_hcd 0000:01:00.0: ERROR Transfer event TRB DMA ptr not part of current TD ep_index 2 comp_code 28
[14:42:22] xhci_hcd 0000:01:00.0: ERROR Transfer event TRB DMA ptr not part of current TD ep_index 2 comp_code 13
```

Decoded: `ep_index 2` is **EP1 IN — the bulk frame-data endpoint**, the very one
`usbmon` shows being cancelled at that moment. `comp_code 28` is *Stopped — Short
Packet*: the endpoint was **stopped** (the xHCI Stop-Endpoint command that implements
URB cancellation) in the middle of a transfer. `comp_code 13` is *Short Packet*. And
the message itself is the xhci driver's consistency check failing: **the controller
returned transfer events for TRBs the driver no longer has in its current TD** — the
controller and the driver disagree about where the ring is, during the cancellation
storm. That is exactly the situation in which the driver falls back to timers to
finish each cancel — the 104.0 ms ladder — and in which an endpoint context can be
left in a state the device never recovers from.

Two more things the log says:

- **The clean stop at 14:34:31 logged five of the same errors** (one code 28, four
  code 13) and did *not* deadlock. So the ring desync happens on every high-rate stop
  on this host; the deadlock is the fraction of them where the aftermath kills EP0.
  That is the probabilistic behaviour in the tally, explained.
- **Nothing is logged from the camera side** — no disconnect, no reset, no babble. The
  device stays enumerated; its control endpoint just stops being served.

Taken together with `usbmon`: the SDK cancels ~15–29 in-flight bulk URBs without
first telling the camera to stop; the ASMedia controller under VFIO mishandles the
cancellation (events for TRBs the driver has dequeued, ~100 ms per unlink); and the
camera's EP0 is dead afterwards. This is a **controller-path problem** — ASM2142 and/or
its passthrough — with the SDK's command-less stop and the camera's reaction as the
other two legs. The physical host, with a different controller and no hypervisor,
never showed it in 18 stops.

**What would settle the remaining ambiguity:** the same `usbmon` + `dmesg` pair on
`psc-razer`. If bare metal shows no `TRB DMA ptr` errors, millisecond cancels and a
completed EP0 read, the VM/controller is the cause and the conversation is with
whoever runs Proxmox: a different USB controller model passed through (Intel or
Renesas rather than ASMedia), IOMMU/interrupt-remapping settings for the VFIO device,
or bare metal for this detector. If bare metal shows the same errors, it is the
ASMedia controller itself, and the fix is still a different controller.

Whichever way that falls, two things are already certain and independent of the
host: Tucsen's stop path must command the camera to stop before cancelling reads, and
every SDK transfer needs a timeout; and this driver must not hold the asyn port lock
across any of them.

## Controller swap — 2026-08-25 16:31: Renesas instead of ASMedia, 10 of 10 clean

After the report above went to management, the detector's USB cable was moved from
the ASMedia ASM2142 PCIe card to a **Renesas uPD720202** USB 3.0 controller on the
hypervisor's motherboard, and that controller was passed through to the same VM
(`0000:01:00.0`, driver `xhci-pci-renesas`, still VFIO). Same VL813 hub, same camera,
same SDK, same driver, same script.

| | ASMedia (morning) | Renesas (16:31) |
|---|---|---|
| Stops at 32 rows | 5, **4 froze** | 10, **0 froze** — then 38 of 38 across every height incl. 8 rows at 3567 fps |
| Frame rate at 32 rows | 861 fps, 226 MB/s | **1037 fps, 272 MB/s** — the physical host measured 1039.6 |
| SDK-reported USB transfer rate at connect | 265 | 285 |

This is the discriminating experiment, done without moving the detector to the lab
machine: **same VM, same hypervisor, same passthrough mechanism — different USB
controller — and the fault is gone, along with most of the "virtualisation" frame-rate
penalty.** The ASMedia controller (as passed through here) was both the deadlock
amplifier and the per-frame throughput loss. The SDK's command-less stop and the
untimed transfers are unchanged and still wrong in principle; they are simply not
being provoked.

Caveats, so this is not oversold: 10 stops is strong but not exhaustive (the ASMedia
also survived a 32-row stop once in five); the full sweep including 8 rows and the
write path then completed clean (38 of 38 stops); and **`dmesg` for the Renesas is
clean** — only the 16:21 boot enumeration lines, nothing at all during the 38 stops
(`~/axis-deadlock-evidence/dmesg-xhci-renesas.txt`), where the ASMedia logged `TRB DMA
ptr not part of current TD` at every fast stop. **Case closed on the cause.** One benign
note in that log: `failed to load renesas_usb_fw.mem, fallback to ROM` — the optional
firmware file is not installed, so the controller runs its built-in ROM firmware, which
evidently works; installing `firmware-misc-nonfree` would let the kernel load the
vendor file instead, but nothing observed calls for it.

## Fix

Three layers, in order of how much they buy:

**1. Never hold the asyn port lock across any SDK call.** Every `TUCAM_*` call ends
in a synchronous libusb transfer with no timeout, and two of them have now been
caught blocking forever under the lock: `TUCAM_Cap_Stop` from `stopCapture()`
(shape 1) and `TUCAM_Prop_GetValue` / `TUCAM_Dev_GetInfo` from the temperature
task (shape 2). Concretely:

- `stopCapture()` does only `TUCAM_Buf_AbortWait` (cheap, wakes the image task) and
  sets the stop flag. The **image task** performs `Cap_Stop` and `Buf_Release` — it
  already calls `Cap_Stop` *outside* the lock in its idle branch, so the pattern
  exists.
- `tempTask` calls the SDK **unlocked** and takes the lock only to store the results
  (`setDoubleParam`, `callParamCallbacks`). Today it holds the lock across both SDK
  calls every 0.5 s, which makes it the most likely thread to be caught.
- The `writeInt32` / `writeFloat64` paths that call `setProperty` / `setCapability`
  / `setROI` have the same exposure — **confirmed** 2026-08-25 13:49, when
  `setProperty` from `writeFloat64(AcquireTime)` hung exactly this way with the poll
  disabled — and need the same treatment, or a bounded worker thread with a timeout.

If the SDK then hangs, one thread strands; the port keeps serving, `SizeY` still
works, `DetectorState` can be set to `Error`, and `exit` still exits.

**2. A liveness watchdog.** `DetectorState` is not usable for this (it read `Idle`
in shape 2). Instead: if the temperature poll has not returned for N seconds, or a
stop has not completed, set `ADStatusError` and a status message naming this
document. That turns a silent hang into a diagnosable one.

**3. Report to Tucsen**, with both stacks: after a stop at high frame rate the
camera stops completing USB transfers, and because every SDK call uses synchronous
libusb transfers with no timeout, `TUCAM_Cap_Stop` (joining a thread in an untimed
bulk read) and `TUCAM_Prop_GetValue` (an untimed control transfer) both block
forever. Bounded transfer timeouts throughout, plus cancelling the pending bulk
read before the join in `FinishBulkInDataTransfer`, would fix it at the source.
Include the VM/bare-metal contrast — it will help them reproduce.

Until 1 is in: **do not run the detector at ROI heights of 128 rows or below
unattended**, and expect a reboot after any stop after which a write no longer
round-trips — `DetectorState` may well read `Idle`.

## See also

- [TODO.md](../known-gaps/TODO.md) §1 — the open item
- [known-gaps/README.md](../known-gaps/README.md)
- [performance/README.md](../performance/README.md) — the sweep that found it, and
  the fail-fast check added to the script
