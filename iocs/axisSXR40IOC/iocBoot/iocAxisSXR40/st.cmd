# st.cmd -- AXIS-SXR-40 IOC
#
# Single canonical startup file. This module builds for one architecture only
# (iocBoot/iocAxisSXR40/Makefile hardcodes ARCH = linux-x86_64), so there is no
# per-platform st.cmd.<os> variant -- a second copy is exactly how the geometry
# below drifted out of step with reality once already.
#
# The geometry is this detector's, and it is measured rather than taken from a
# data sheet: TUIDI_CURRENT_WIDTH and TUIDI_CURRENT_HEIGHT both read 4096, and
# Buf_Alloc reports uiImgSize = 33554432. See info/dhyana-xfxv4040bsi.md in the
# DISCO support repository.
#
#   full frame   4096 x 4096, 16-bit mono, 1 channel  ->  32 MiB per frame
#   throughput   ~289 MB/s measured                   ->  ~8.6 fps
#   SDK ring     2 frames deep, ~230 ms of slack      ->  watch AXIS_BUFF_FRAMES
#
# 4096 x 4096 is the maximum; TUIDC_RESOLUTION modes 1 and 2 are 2x2 and 4x4
# binned (2048^2, 1024^2), so nothing here ever needs to be larger.

< envPaths
errlogInit(20000)

dbLoadDatabase("$(TOP)/dbd/axisSXR40App.dbd")
axisSXR40App_registerRecordDeviceDriver(pdbbase)

# Prefix for all records
epicsEnvSet("PREFIX", "AXIS:SXR40:")
# The port name for the detector
epicsEnvSet("PORT",   "AXISSXR40")
# The camera number in the system
epicsEnvSet("CAMERA", "0")
# The queue size for all plugins. A queued NDArray is a refcounted pointer, not a
# copy, so this bounds queue depth rather than memory directly -- but at 32 MiB
# per frame a backed-up chain still grows the driver's NDArrayPool fast, and
# maxBuffers/maxMemory are capped in axisSXR40Config below.
epicsEnvSet("QSIZE",  "21")
# The maximum image width; sizes row profiles in NDPluginStats and the 1-D FFT.
# Must match the sensor.
epicsEnvSet("XSIZE",  "4096")
# The maximum image height; sizes column profiles in NDPluginStats.
epicsEnvSet("YSIZE",  "4096")
# The maximum number of time series points in the NDPluginStats, NDPluginROIStats
# and NDPluginAttribute plugins. This is a time series length, unrelated to image
# size -- it does not need to track XSIZE/YSIZE.
epicsEnvSet("NCHANS", "2048")
# The maximum PreCount allowed in NDPluginCircularBuff. Nothing is preallocated,
# but 500 frames of this detector would be 16 GB if a user asked for it.
epicsEnvSet("CBUFFS", "500")
# The maximum number of threads for plugins which can run in multiple threads
epicsEnvSet("MAX_THREADS", "8")
# The search path for database files
epicsEnvSet("EPICS_DB_INCLUDE_PATH", "$(ADCORE)/db")

# EPICS_CA_MAX_ARRAY_BYTES is deliberately not set. EPICS Base 7.0.10 defaults to
# EPICS_CA_AUTO_ARRAY_BYTES=YES, which sizes CA network buffers automatically and
# ignores it (see epics-base/documentation/RELEASE-3.16.md). Only a client or IOC
# that explicitly sets EPICS_CA_AUTO_ARRAY_BYTES=NO needs
# EPICS_CA_MAX_ARRAY_BYTES >= 33554432 (4096*4096*2) to read image1:ArrayData.

asynSetMinTimerPeriod(0.001)

# axisSXR40Config(const char *portName, int cameraId, int traceMask,
#                 int maxBuffers, size_t maxMemory, int priority, int stackSize)
#
# Argument 3 is traceMask, NOT maxBuffers -- upstream ADTucsen's comment listed a
# different 7-argument signature ending in maxFrames, which does not exist here.
# 0x1 = ASYN_TRACE_ERROR. priority and stackSize 0 take the asyn defaults.
#
# maxMemory is deliberately NOT 0 (unlimited). At 32 MiB per frame an unbounded
# NDArrayPool is a real way to lose an experiment: plugins hold refcounted
# references while their queues drain, so a stalled plugin (slow NFS write, blocked
# client) accumulates frames at ~288 MB/s. This host has 15 GB, so that reaches the
# OOM killer in well under a minute and takes the IOC down mid-acquisition.
#
#   maxMemory 1610612736 = 1.5 GiB = 48 frames = ~5 s of full-rate acquisition
#
# Since ADCore R3-3 this ONE number bounds the driver *and every downstream plugin*
# together -- plugins allocate from the driver's pool, not their own (ADCore
# RELEASE.md, "NDArrayPool design changes"). That is what makes it the right lever:
# it is the sum across the chain that matters, not per-plugin limits.
#
# maxBuffers is passed as 0 because ADCore R3-3 and later IGNORE it entirely -- "The
# maxBuffers argument to all driver and plugin constructors is now ignored. There is
# now no limit on the number of NDArrays, only on the total amount of memory." Do not
# expect a non-zero value here to do anything.
#
# Bounded means a stall produces a failed alloc and a stopped acquisition with an
# error, which is recoverable, instead of a dead host. Raise it rather than removing
# it if normal operation ever approaches the cap; with ~11 GB free there is room.
#
# Checking it is in force is not obvious: $(P)$(R)PoolMaxMem is SCAN="Passive" with
# PINI="YES" in ADCore's NDArrayBase.template, so it latches 0 at iocInit and never
# updates. It reads correctly only after
#   caput $(PREFIX)cam1:PoolPollStats 1 ; caput $(PREFIX)cam1:PoolMaxMem.PROC 1
# PoolUsedMem and PoolAllocBuffers are I/O Intr and do track live.
axisSXR40Config("$(PORT)", $(CAMERA), 0x1, 0, 1610612736, 0, 0)

# axisSXR40.template includes ADBase.template, so ADBase is not loaded separately
dbLoadRecords("$(ADAXISSXR40)/db/axisSXR40.template", "P=$(PREFIX),R=cam1:,PORT=$(PORT),ADDR=0,TIMEOUT=1")

# Create a standard arrays plugin
NDStdArraysConfigure("Image1", 5, 0, "$(PORT)", 0, 0)
# NELEMENTS must be at least 4096*4096 = 16777216. Upstream's 5600000 was sized
# for a 2048^2 camera and would silently truncate every image from this one.
# 16-bit matches the sensor's native depth; use the Int32 line instead only if a
# plugin chain in accumulate mode would overflow 16 bits.
#dbLoadRecords("$(ADCORE)/db/NDStdArrays.template", "P=$(PREFIX),R=image1:,PORT=Image1,ADDR=0,TIMEOUT=1,NDARRAY_PORT=$(PORT),TYPE=Int32,FTVL=LONG,NELEMENTS=16777216")
dbLoadRecords("$(ADCORE)/db/NDStdArrays.template", "P=$(PREFIX),R=image1:,PORT=Image1,ADDR=0,TIMEOUT=1,NDARRAY_PORT=$(PORT),TYPE=Int16,FTVL=SHORT,NELEMENTS=16777216")

# Load all other plugins using commonPlugins.cmd
< $(ADCORE)/iocBoot/commonPlugins.cmd
set_requestfile_path("$(ADAXISSXR40)/axisSXR40App/Db")
# commonPlugins.cmd leaves set_requestfile_path("$(CALC)/db") commented out, so
# every save cycle logged "save_restore:readReqFile: unable to open file
# sseq_settings.req" 11 times. The file is in $(CALC)/db; adding the path is
# harmless and silences it.
set_requestfile_path("$(CALC)/db")

asynSetTraceIOMask("$(PORT)",0,4)
# reportCapabilitySupport() logs its summary at ASYN_TRACE_ERROR, so the one line
# worth seeing appears without tracing enabled. Add ASYN_TRACE_FLOW (0x8) for the
# per-id supported/NOT SUPPORTED list.
#asynSetTraceMask("$(PORT)",0,9)
#asynSetTraceMask("$(PORT)",0,255)

# Default output filename patterns.
#
# FileTemplate is PINI=YES but ADCore's NDFile.template gives it no default VAL --
# it carries info(autosaveFields,"VAL") and lives in NDFile_settings.req, so its
# value is expected to come from autosave. On a fresh autosave/ directory there is
# nothing to restore and it comes up EMPTY, which makes FullFileName resolve to
# nothing and every writer fail with "Error opening file , status=3" -- a message
# that never mentions the template, so it reads as a path or permission fault.
#
iocInit()

# These must come after iocInit -- dbpf refuses to run before it ("dbpf only works
# after iocInit"), so they cannot be made autosave-overridable defaults. They are
# re-asserted on every boot, which means a pattern changed at runtime will not
# survive a restart. Accepted deliberately: a filename pattern is rarely tuned,
# and an empty one is a hard failure reported in a way that misdirects.
dbpf("$(PREFIX)TIFF1:FileTemplate",   "%s%s_%3.3d.tif")
dbpf("$(PREFIX)HDF1:FileTemplate",    "%s%s_%3.3d.h5")
dbpf("$(PREFIX)JPEG1:FileTemplate",   "%s%s_%3.3d.jpg")
dbpf("$(PREFIX)netCDF1:FileTemplate", "%s%s_%3.3d.nc")

# save things every thirty seconds
create_monitor_set("auto_settings.req", 30, "P=$(PREFIX)")
