"""What the suite may write, and what it snapshots and restores.

Names are relative to the IOC prefix. `ca.CA.put()` refuses anything not in
SAFE_WRITES, and refuses everything in FORBIDDEN_WRITES even if it were added to
SAFE_WRITES by mistake. Restore order matters and is the order of SNAPSHOT_PVS.
"""

# Controls that touch cooling hardware, external trigger lines, the shutter, or the
# 8 SDK ids this camera does not implement. Never written by any test.
FORBIDDEN_WRITES = frozenset({
    "cam1:TECEnable", "cam1:Temperature", "cam1:FanGear",
    "cam1:ShutterControl", "cam1:ShutterMode",
    *[f"cam1:TriggerOut{n}{s}" for n in (1, 2, 3) for s in ("Mode", "Edge", "Delay", "Width")],
    "cam1:AutoExposure", "cam1:GainMode", "cam1:DefectCorrection", "cam1:Enhance",
    "cam1:BlackLevel", "cam1:Brightness", "cam1:Sharpness", "cam1:HDRK",
})

SAFE_WRITES = frozenset({
    # acquisition
    "cam1:Acquire", "cam1:ImageMode", "cam1:NumImages", "cam1:AcquireTime",
    "cam1:AcquirePeriod", "cam1:ArrayCounter", "cam1:ArrayCallbacks",
    # geometry
    "cam1:MinX", "cam1:MinY", "cam1:SizeX", "cam1:SizeY", "cam1:BinMode",
    # trigger (input side only; software trigger needs no hardware)
    "cam1:TriggerMode", "cam1:TriggerEdge", "cam1:TriggerExposure", "cam1:TriggerDelay",
    "cam1:SoftwareTrigger",
    # image processing knobs the camera implements (restored afterwards)
    "cam1:AutoLevels", "cam1:Histogram", "cam1:FrameFormat", "cam1:ReverseX", "cam1:ReverseY",
    "cam1:Gain", "cam1:Gamma", "cam1:Contrast", "cam1:NoiseLevel",
    "cam1:LeftLevels", "cam1:RightLevels", "cam1:EnableDenoise", "cam1:DynRgeCorrection",
    "cam1:FlatCorrection",
    # pool statistics
    "cam1:PoolPollStats", "cam1:PoolMaxMem.PROC",
    # file writers
    "HDF1:EnableCallbacks", "HDF1:FilePath", "HDF1:FileName", "HDF1:FileTemplate",
    "HDF1:FileWriteMode", "HDF1:NumCapture", "HDF1:AutoIncrement", "HDF1:AutoSave",
    "HDF1:Compression", "HDF1:Capture", "HDF1:DroppedArrays", "HDF1:FileNumber",
    # stress tier: compression knobs and the writer queue (QueueSize recreates the plugin threads)
    "HDF1:ZLevel", "HDF1:BloscCompressor", "HDF1:BloscShuffle", "HDF1:BloscLevel",
    "HDF1:QueueSize", "HDF1:BlockingCallbacks", "HDF1:NumFramesFlush", "HDF1:StorePerform", "HDF1:StoreAttr",
    "TIFF1:EnableCallbacks", "TIFF1:FilePath", "TIFF1:FileName", "TIFF1:FileTemplate",
    "TIFF1:FileWriteMode", "TIFF1:AutoSave", "TIFF1:AutoIncrement", "TIFF1:FileNumber",
    "TIFF1:WriteFile",
    # plugins used by tests
    "Stats1:ComputeStatistics", "Stats1:EnableCallbacks", "image1:EnableCallbacks",
    "Pva1:EnableCallbacks", "image1:DroppedArrays", "Pva1:DroppedArrays", "Stats1:DroppedArrays",
})

assert not (SAFE_WRITES & FORBIDDEN_WRITES), "a PV cannot be both safe and forbidden"

# Snapshotted at session start (and per test on request), restored in THIS order.
#   - BinMode before geometry: writing it re-runs setROI.
#   - offsets before sizes: a size written against a non-zero offset is clamped and
#     never re-expands (roi-rate-test.sh NOTE 2).
#   - AutoLevels before Histogram: AutoLevels forces Histogram.
SNAPSHOT_PVS = (
    "cam1:ImageMode", "cam1:NumImages", "cam1:AcquireTime", "cam1:AcquirePeriod",
    "cam1:ArrayCallbacks",
    "cam1:TriggerMode", "cam1:TriggerEdge", "cam1:TriggerExposure", "cam1:TriggerDelay",
    "cam1:BinMode",
    "cam1:MinX", "cam1:MinY", "cam1:SizeX", "cam1:SizeY",
    "cam1:AutoLevels", "cam1:Histogram",
    "cam1:FrameFormat", "cam1:ReverseX", "cam1:ReverseY",
    "cam1:Gain", "cam1:Gamma", "cam1:Contrast", "cam1:NoiseLevel",
    "cam1:LeftLevels", "cam1:RightLevels", "cam1:EnableDenoise", "cam1:DynRgeCorrection",
    "cam1:FlatCorrection",
    "cam1:PoolPollStats",
    "HDF1:QueueSize", "HDF1:BlockingCallbacks",      # restored only if changed (thread recreation)
    "HDF1:EnableCallbacks", "HDF1:FilePath", "HDF1:FileName", "HDF1:FileTemplate",
    "HDF1:FileWriteMode", "HDF1:NumCapture", "HDF1:AutoIncrement", "HDF1:AutoSave",
    "HDF1:Compression", "HDF1:ZLevel", "HDF1:BloscCompressor", "HDF1:BloscShuffle", "HDF1:BloscLevel",
    "HDF1:StorePerform", "HDF1:StoreAttr", "HDF1:FileNumber",     # NumFramesFlush: the plugin rewrites it itself
    "TIFF1:EnableCallbacks", "TIFF1:FilePath", "TIFF1:FileName", "TIFF1:FileTemplate",
    "TIFF1:FileWriteMode", "TIFF1:AutoSave", "TIFF1:AutoIncrement", "TIFF1:FileNumber",
    "Stats1:ComputeStatistics", "Stats1:EnableCallbacks", "image1:EnableCallbacks",
    "Pva1:EnableCallbacks",
)
assert set(SNAPSHOT_PVS) <= SAFE_WRITES, "everything we restore must be writable"

# Setpoints whose readback is NOT simply <name>_RBV, or which have no readback.
NO_RBV = frozenset({"cam1:Acquire", "cam1:ArrayCounter", "cam1:SoftwareTrigger",
                    "cam1:PoolPollStats", "cam1:PoolMaxMem.PROC",
                    "HDF1:Capture", "HDF1:DroppedArrays", "image1:DroppedArrays",
                    "Pva1:DroppedArrays", "Stats1:DroppedArrays", "TIFF1:WriteFile"})

# busy records: a put WITH completion callback blocks until the record goes back to 0
# (capture finished, acquisition finished). With NumCapture 0 that is never; the CA server
# logs "put call back time out" and the client's channels degrade. Always written without
# a callback (the shell scripts used caput without -c for the same reason).
NO_CALLBACK = frozenset({"cam1:Acquire", "HDF1:Capture", "TIFF1:Capture", "TIFF1:WriteFile", "HDF1:WriteFile"})

# Float setpoints: readback compared with a tolerance (relative, then absolute).
FLOAT_TOL = {"cam1:AcquireTime": 1e-4, "cam1:AcquirePeriod": 1e-4, "cam1:TriggerDelay": 1e-6}
DEFAULT_REL_TOL = 1e-3

# Writing these recreates the plugin's threads and message queue (ADCore R3-14
# NDPluginDriver::writeInt32), discarding queued arrays. Restore writes them only when the
# readback differs from the snapshot, so an ordinary restore never touches them.
RESTORE_ONLY_IF_CHANGED = frozenset({"HDF1:QueueSize", "HDF1:BlockingCallbacks"})

# ---- IOC log watching (helpers/logdelta.py) --------------------------------------------
# A line is flagged when it matches an error pattern and no allow pattern.
LOG_ERROR_PATTERNS = (
    r"(?i)\berror\b", r"(?i)\bfail(ed|ure)\b", r"Segmentation|double free|corruption",
    r"NDArrayPool alloc failed|out of memory", r"Invalid frame", r"data size mismatch",
    r"cantProceed", r"failed to wait for buffer", r"Failed to start image capture",
)
LOG_ALLOW_PATTERNS = (
    r"^\s*#",                                   # iocsh echo of st.cmd comments
    r"^@@@",                                     # procServ
    r"capability audit",
    r"\[BeginBulkInDataTransfer\]", r"\[OpenPhxCore\]", r"\[PhxCoreOpen\]",
    r"Finished thread!", r"perform_data_acquire",
    # autosave replaying the 8 unsupported controls at boot (boot/ checks the exact set)
    r"cam1:(Brightness|BlackLevel|Sharpness|HDRK|GainMode|AutoExposure|Enhance|DefectCorrection) devAsyn",
    r"unable to (set|get) (property|capability) (2|3|5|7|12|13|22)\b",
    r"write(Int32|Float64):? error, status=3 function=",
)
