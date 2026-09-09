# AXIS-SXR-40 detector: why the IOC freezes after a fast stop, and what we found

**Date:** 2026-08-25 · **Host:** `bl1101ad01` (Proxmox VM) · **Detector:** AXIS-SXR-40 s/n 702, Tucsen Dhyana XF/XV4040BSI camera `KBSG09024003`, SDK 2.0.7.0
**Prepared by:** Gabriel Gazolla, with analysis assistance from Claude · **Full technical write-up:** [stop-deadlock.md](stop-deadlock.md)

---

## 1. Summary

When the detector is told to **stop** while it is acquiring at **high frame rate** (small
region-of-interest, hundreds of frames per second), the EPICS control software
sometimes **freezes**: it looks alive from outside, but no command reaches the camera
again, no images flow, and only a **reboot of the VM** recovers it.

We traced this all the way down to the USB wire and the kernel's own log. The chain is:

1. The vendor's software library stops the camera by **abandoning its pending reads,
   without ever telling the camera to stop**.
2. On our VM, the **passed-through USB controller mishandles that abrupt stop** — the
   Linux kernel logs controller errors at the exact moment, and each pending transfer
   takes 100 ms to unwind instead of about 1 ms.
3. Afterwards the camera **stops answering any request at all**. The vendor library
   waits forever for an answer, and because both EPICS drivers make that call while
   holding their one internal lock, the whole IOC is stuck.

It happens in **both** drivers (ours and the ADTucsen-based one), it is **not** caused by
our own code, and the **physical lab machine never does it** (0 of 18 stops, versus
5 of 7 fast stops here). The most likely root cause is the combination of the vendor's
command-less stop with the ASMedia USB controller under Proxmox PCI passthrough.

Normal operation — full frame, ~9 fps, or anything down to 256 rows — **never failed**
in 20 stops. There is **no data corruption and no hardware damage**; the cost is a
reboot and the loss of unattended operation at small ROIs until it is fixed.

---

## 2. How the detector is connected

```
Tucsen camera (inside the AXIS enclosure, in vacuum)
   │  fiber
fiber → USB 3 converter   (appears to the PC as a VIA Labs VL813 4-port hub)
   │  USB 3
ASMedia ASM2142 USB 3.1 controller card, in the Proxmox server
   │  PCI passthrough (VFIO) — the whole card is handed to one VM
this VM, bl1101ad01  →  Linux kernel USB stack  →  Tucsen SDK (libTUCam)  →  EPICS driver
```

The physical lab machine (`psc-razer`, where the July measurements were made) has the
camera on its own on-board USB controller, with no hypervisor in between.

---

## 3. What happens, in plain words

A USB camera talks to the PC over two channels on one cable: a **firehose** for the
frame data, and a small **intercom** for short questions and answers ("what's your
temperature?", "set exposure", "who are you?"). Inside the camera a small computer
runs the vendor's firmware and does both jobs.

Because the firehose is fast, the PC hands its USB controller a stack of **empty
buckets** in advance — "fill these as frames arrive". At 860 frames per second,
several buckets are being filled at any moment.

**The vendor library stops the camera by taking the buckets away.** It does not say
"stop" over the intercom. The camera does not know, and keeps pushing frames.

Taking away a bucket that is currently being filled is a delicate operation for the
controller chip. On our VM the controller gets it wrong: the kernel records that the
controller reported transfers the driver had already thrown away — the two sides lost
track of where they were. Each bucket removal then took **100 ms** (a give-up timer)
instead of a millisecond; with ~29 buckets that is **1.5 seconds** of the camera
pushing data into a pipe that is being torn down.

After that, the intercom is dead. The PC asks "what's your temperature?" and gets
**silence, forever** — not an error, no reply. The vendor library has no timeout on
that question, so it waits forever. Our driver asked the question while holding the
lock that every other command needs, so **everything else queues behind it**: the IOC
is frozen while still reporting `Idle`.

At low frame rates none of this happens. There is one bucket in play, usually idle,
and the stop lands in a quiet gap between frames. That is why full-frame operation
never fails and 32-row operation fails four times in five.

---

## 4. Evidence

Everything below was measured on 2026-08-25 on `bl1101ad01`. Raw files are in
`~/axis-deadlock-evidence/` on that host.

### 4.1 It is reproducible, and frame rate is what matters

Every failure is an `Acquire = 0` (stop) after continuous acquisition. Tally by the
ROI height that was being acquired when the stop was issued:

| Acquiring at | Frame rate | Stops | Froze |
|---|---|---|---|
| 4096 … 256 rows (5 heights) | 8 – 128 fps | 20 | **0** |
| 128 rows | 240 fps | 3 | 1 |
| 64 rows | 430 fps | 2 | 0 |
| 32 rows | 860 fps | 5 (both drivers) | **4** |
| 8 rows | 1500 fps | 2 | 1 |
| **Physical lab machine, 2026-07-29, all heights incl. 32 and 8** | | **18** | **0** |

Changing the ROI is not the trigger — the ROI is always changed while stopped. The
ROI only sets how fast the camera is streaming when the stop arrives.

### 4.2 It is not specific to our driver

The same test was run against the unmodified upstream ADTucsen IOC (Damon's). Its
**first** stop at 32 rows froze it, with the identical signature (`asynReport`:
`synchronousLock:Yes nQueued 8`; frame counter frozen; writes never processed).

### 4.3 It is not caused by our temperature polling

Our driver polls the camera temperature every 0.5 s. We disabled that poll entirely
(`AXIS_NO_TEMP_POLL=1`) and repeated the test: the camera went silent after the first
32-row stop exactly as before, and the *next* command to the camera (an exposure
write) hung instead. The poll is merely the request most often in flight when the
camera dies — a victim, not a cause.

### 4.4 Where the software is stuck (debugger)

Attaching `gdb` to the frozen IOC — four times, in three variants — always shows the
same thing: a thread inside the vendor library, inside `libusb`, in `poll()`, waiting
for a USB transfer that never completes, while holding the driver's lock.

```
Thread "AxisSXR40TempRe"  -- holding the port lock
#3  poll()
#7  sync_transfer_wait_for_completion       libTUCam.so.1
#8  libusb_control_transfer                 libTUCam.so.1   <- a 4-byte "read temperature" request
#9  CTUDrvCypress::CommitURB                libTUCam.so.1
#12 CTUCamBase::GetPropertyValue            libTUCam.so.1
#13 axisSXR40::tempTask                     axisSXR40.cpp:1386

Thread "AXISSXR40"  -- the EPICS port thread, waiting for that lock; 1 to 8 commands queued behind it
#4  asynPortDriver::lock
#5  writeInt32                              (the operator's next command)
```

In the other variants the stuck call was `TUCAM_Cap_Stop` itself (the stop, joining a
transfer thread parked in an untimed bulk read) and `TUCAM_Prop_SetValue` (an exposure
write). Different calls, same fate: **every vendor SDK call is a synchronous USB
transfer with no timeout.**

### 4.5 What went over the USB wire (kernel `usbmon` capture)

One freeze was captured end to end with the kernel's USB monitor (**0 events dropped**).
Times are seconds; `S` = submitted, `C` = completed; `Bi…:1` is the frame-data
endpoint, `Ci…:0` / `Co…:0` the intercom (in / out).

```
… healthy stream: a 262 152-byte frame every 1.16 ms, every one status 0 …
4142.7759  C Bi:10:3:1  st=0    len=262152      last good frame
4142.7765  C Bi:10:3:1  st=-2   len=0           stop begins: -2 = cancelled by the host  (×29,
4142.7787  C Bi:10:3:1  st=-2   len=232448        two of them cut in mid-transfer)
4142.7791  C Bi:10:3:1  st=-2   len=23552
4142.8437  C Bi:10:3:1  st=-2   len=0           then 15 more cancellations arriving
4142.9447  C Bi:10:3:1  st=-2   len=0             104.0 ms apart, regular to 0.1 ms
   …                                              (should take ~1 ms each)
4144.2967  C Bi:10:3:1  st=-2   len=0           last cancellation, 1.52 s after the first
4144.2971  S Ci:10:3:0  len=4                   "read temperature" submitted 0.35 ms later
                                                 -- NEVER COMPLETED. No C, no error. This is
                                                    the request gdb shows the driver waiting on.
```

Two facts from this trace:

- **No stop command was sent to the camera.** All 8 `Co` (command) transfers in the
  capture occurred during point setup, ten seconds earlier. At the stop: none.
- **The hang is a genuinely outstanding request**, not an error the library ignored.

### 4.6 What the kernel's USB controller driver logged at the same instant

```
[14:42:22] xhci_hcd 0000:01:00.0: ERROR Transfer event TRB DMA ptr not part of current TD ep_index 2 comp_code 28
[14:42:22] xhci_hcd 0000:01:00.0: ERROR Transfer event TRB DMA ptr not part of current TD ep_index 2 comp_code 28
[14:42:22] xhci_hcd 0000:01:00.0: ERROR Transfer event TRB DMA ptr not part of current TD ep_index 2 comp_code 28
[14:42:22] xhci_hcd 0000:01:00.0: ERROR Transfer event TRB DMA ptr not part of current TD ep_index 2 comp_code 13
```

Decoded:

| Field | Meaning |
|---|---|
| `xhci_hcd 0000:01:00.0` | the ASMedia ASM2142 controller passed through to this VM |
| `ep_index 2` | endpoint 1 IN — **the frame-data endpoint being cancelled at that moment** |
| `comp_code 28` | *Stopped – Short Packet*: the endpoint was stopped in the middle of a transfer |
| `comp_code 13` | *Short Packet* |
| `TRB DMA ptr not part of current TD` | the kernel's consistency check failing: **the controller reported a transfer the driver had already discarded** — the two disagree about the state of the ring |

Five identical errors were also logged at **14:34:31**, a fast stop that did *not*
freeze. So the controller mishandles every fast stop on this host; the freeze is the
fraction of them in which the camera's intercom does not survive the aftermath.
Nothing at all is logged from the camera's side — no disconnect, no reset.

### 4.7 Recovery behaviour (why we think something stateful is stuck)

| Action after a freeze | Result |
|---|---|
| Stop the IOC normally (`exit`, `SIGTERM`) | hangs — needs the same lock |
| Kill the IOC (`SIGKILL`) | IOC gone; camera still enumerated but answers nothing |
| Reset the camera's USB port (root) | camera answers "who are you?" again, but the next attempt to start the firehose hangs |
| Reset the whole USB controller (root) | same |
| **Reboot the VM** | **full recovery, 4 of 4** — the only thing that has worked |
| Power-cycle the detector | not required (never needed today) |

---

## 5. What it means for operations

- **Safe:** full-frame operation and any ROI of 256 rows or more (0 failures in 20).
  Changing ROI is safe. All the performance measurements in
  [performance/](../performance/) are unaffected.
- **Not safe unattended:** acquiring at 128 rows or fewer, because the stop that
  inevitably follows can freeze the IOC.
- **Recovery:** reboot the VM (about 2 minutes). Nothing is damaged; no data is
  corrupted — acquisition simply stops.
- **Detection:** the frozen IOC still reports `Idle`. The reliable check is whether a
  write round-trips; our test script now does exactly that after every stop.

---

## 6. What we recommend

**1. Driver hardening — ours and Damon's, cheap, do regardless.** Never call the vendor
library while holding the driver's lock. This does not prevent the camera from
locking up, but it keeps the IOC alive and controllable, reports the fault instead of
hiding it, and lets `exit` work. Every IOC that froze today would have stayed up.

**2. Infrastructure — the likely real fix.** Pass a different USB controller through to
the VM (Intel or Renesas rather than ASMedia), review IOMMU / interrupt-remapping
settings for the VFIO device, or put this detector on bare metal.

**3. Vendor report to Tucsen.** Their stop should command the camera before cancelling
reads, and their USB transfers need timeouts. We have a complete evidence package
(traces, kernel log, stack dumps).

**The one experiment that settles the infrastructure question:** run the same
10-stop test at 32 rows on the physical lab machine with the same `usbmon` and `dmesg`
capture. If the cancellations complete in milliseconds, no controller errors appear,
and the intercom survives, the VM is the cause.

---

## 7. Update, 16:31 — the fix was confirmed the same afternoon

After this report was discussed, the detector's USB cable was moved from the ASMedia
PCIe card to a **Renesas uPD720202** USB 3.0 controller on the hypervisor's motherboard,
and that controller was passed through to the same VM. Nothing else changed: same VM,
same hub, same camera, same software, same test.

| | ASMedia (morning) | Renesas (16:31) |
|---|---|---|
| Stops at 32 rows | 5 — **4 froze** | 10 — **none froze** |
| Stops, all heights incl. 8 rows at 3567 fps (full benchmark + 10 extra) | 5 of 7 fast stops froze | **38 of 38 clean** |
| Frame rate at 32 rows | 861 fps | **1037 fps** (the lab machine: 1040) |

The freeze is gone, and so is most of the frame-rate penalty we had attributed to
virtualisation. **The ASMedia controller was the problem.** The vendor's command-less
stop and untimed USB calls are still design flaws worth reporting, and the driver
hardening is still worth doing as insurance — but the operational risk is resolved by
the hardware change. The full benchmark was repeated under the new controller: every height, both modes,
no freeze, and acquisition speed equal to the lab machine at every height. The kernel
log for the Renesas controller shows **no errors at all** during the 38 stops — where
the ASMedia had logged controller errors at every fast stop. The cause is settled.

## 8. What is certain and what is inferred

| Certain (measured) | Inferred (strong evidence, not proof) |
|---|---|
| The vendor stop sends no stop command; it cancels reads | The VM's passed-through controller is *why* it fires here and not on bare metal |
| Kernel logs controller errors on the frame endpoint at the exact instant of every fast stop | The camera firmware stalls holding a half-delivered frame it was never told to abandon |
| After a bad stop the camera answers nothing; only a reboot recovers it | |
| Both drivers freeze identically because they hold a lock across the vendor call | |
| Frame rate governs probability: 0/20 at ≥256 rows, 4/5 at 32 rows | |
| Our own temperature polling is not the cause (disabled: same failure) | |

---

## Appendix A — Evidence files (`~/axis-deadlock-evidence/` on `bl1101ad01`)

| File | Contents |
|---|---|
| `usbmon-bus10-dev3-20260825-144046.txt` | full USB trace of the 14:42 freeze (14 061 events, 0 dropped) |
| `usbmon-excerpt-stop-and-hang-1442.txt` | the last 60 camera events — the stop and the unanswered request |
| `dmesg-xhci-1442.txt` | kernel USB-controller log for the session |
| `gdb-all-threads-2026-08-25-*.txt` and `gdb-trimmed-*.txt` | debugger stack dumps of four freezes (three variants) |
| `~/axis-perf-results/adtucsen-control-*.log` | the ADTucsen (Damon's driver) reproduction |
| `~/axis-perf-results/stop-test-*.log`, `vm-sweep2-*.log` | the stop tests and the performance sweep |

## Appendix B — Glossary

| Term | Plain meaning |
|---|---|
| **IOC** | the EPICS control program for the detector |
| **SDK / libTUCam** | Tucsen's vendor library that talks to the camera |
| **USB endpoint** | one channel on the USB cable; the camera has a data endpoint (frames) and a control endpoint (commands) |
| **URB / TRB / TD** | units of USB work the kernel hands to the controller — "buckets" |
| **xHCI** | the USB 3 controller standard; `xhci_hcd` is the Linux driver for it |
| **VFIO / PCI passthrough** | handing a whole hardware card from the Proxmox host to one VM |
| **`usbmon`** | the Linux kernel's built-in USB traffic recorder |
| **deadlock** | two parts of a program each waiting for the other; nothing moves |
