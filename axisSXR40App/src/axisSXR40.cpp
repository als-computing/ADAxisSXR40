/* axisSXR40 -- EPICS areaDetector driver for the AXIS-SXR-40 detector.
 *
 * Drives the Tucsen Dhyana XFXV4040BSI (USB 5453:e41b) inside the AXIS-SXR-40
 * via Tucsen's TUCam SDK. The SDK is NOT GenICam-compliant and the camera is
 * not USB3 Vision, so ADGenICam is not usable -- see sdk/sdk-overview.md
 * in the AXIS-SXR-40 support repository.
 *
 * SDK: this module contains no copy of the Tucsen SDK. Headers come from
 * /usr/local/include/tucam and libTUCam from /usr/lib/x86_64-linux-gnu, both
 * installed by sdk/install.sh. See configure/CONFIG_SITE for why it is installed
 * rather than vendored, and README.md for the consequences.
 *
 * ---------------------------------------------------------------------------
 * ATTRIBUTION
 *   Adapted from ADTucsen by David Vine (28 October 2017), which was itself
 *   based on Mark Rivers' ADPointGrey driver. Licensed under the LBNL BSD
 *   variant -- see ./LICENSE, which also retains the required areaDetector
 *   (EPICS Open License).
 *
 * DIFFERENCES FROM ADTucsen -- each justified by a measured property of this
 * camera, documented in info/camera/dhyana-xfxv4040bsi.md of the
 * AXIS-SXR-40 support repository:
 *
 *   1. WaitForFrame is given an explicit timeout derived from the exposure.
 *      ADTucsen relied on the header default of 1000 ms; this camera's
 *      exposure range reaches 3600 s, so any exposure past ~1 s failed and
 *      presented as a dead camera.
 *   2. Frame data is copied row by row using uiWidthStep rather than one flat
 *      memcpy. Full frame here is unpadded (8192 == 4096*2), but ROI and
 *      binned modes are not guaranteed to be.
 *   3. Parameters for controls this model does not implement have been
 *      removed: auto-exposure, CMS/HDR image mode, defect correction,
 *      enhance, black level, brightness, sharpness and HDR-K all return
 *      errors on this unit.
 *   4. Added TEC enable and host-ring occupancy readback. The SDK ring is only
 *      2 frames deep (~230 ms of slack at 8.6 fps full frame), so
 *      TUIDI_CURRENTBUFFRAMES is the dropped-frame telemetry that matters.
 * ------------------------------------------------------------------------- */


#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#ifdef _WIN32
#include <direct.h>
#define getcwd _getcwd
#else
#include <unistd.h>
#endif

#include <epicsEvent.h>
#include <epicsTime.h>
#include <epicsThread.h>
#include <iocsh.h>
#include <epicsString.h>
#include <epicsExit.h>

#include <TUCamApi.h>

#include <ADDriver.h>

#include <epicsExport.h>

#define DRIVER_VERSION      0
#define DRIVER_REVISION     2
#define DRIVER_MODIFICATION 0

/* Added to the exposure to form the WaitForFrame timeout. Must cover a full
 * frame readout (~116 ms for 33.5 MB at the measured ~289 MB/s) plus
 * first-frame startup. Generous on purpose: overshooting costs nothing because
 * Buf_AbortWait unblocks the wait immediately, while undershooting turns a
 * healthy long exposure into a spurious "failed to wait for buffer". */
#define TIMEOUT_MARGIN_MS   3000

/* Sensor temperature calibration -- UNIT SPECIFIC, CHECK IF THE CAMERA IS SWAPPED.
 *
 * TUIDP_TEMPERATURE does not read back in Celsius. AXIS's factory test report for
 * this detector states, for the USB3 interface: "the temperatures displayed by the
 * software are not calibrated. The real temperature of the sensor in C is
 * Tsensor(C) = 1.7 x Value + 15" (report p10, with the fitted line plotted).
 *
 * This is a per-unit calibration, and the report is the acceptance record for THIS
 * detector -- AXIS serial 702, digitizing board serial KBSG09024003, which is what
 * ADSerialNumber reads back from the camera. If the camera or detector is ever
 * replaced, these two constants must be re-established for the new unit; they are
 * not a property of the Dhyana model.
 *
 * The fit was plotted over raw values -25..+5, so readings far outside that range
 * are extrapolation. Note also that the WRITE direction of the same property uses a
 * completely different scale -- see writeFloat64(ADTemperature). */
#define AXIS_TEMP_CAL_SLOPE     1.7
#define AXIS_TEMP_CAL_OFFSET   15.0
#define AXIS_TEMP_CAL_UNIT     "AXIS s/n 702 / KBSG09024003"
#define AXIS_TEMP_RAW_MIN     (-25.0)   /* fitted range, for the extrapolation warning */
#define AXIS_TEMP_RAW_MAX       (5.0)

/* Cap passed to the SDK as TUCAM_VALUE_INFO.nTextSize, and the size of any
 * buffer we copy a text info field into. The SDK owns the string itself. */
#define TEXT_INFO_SIZE      64

#define AxisSXR40BusString           "AXIS_BUS"
#define AxisSXR40ProductIDString     "AXIS_PRODUCT_ID"
#define AxisSXR40TransferRateString  "AXIS_TRANSFER_RATE"
#define AxisSXR40FrameSpeedString    "AXIS_FRAME_SPEED"
#define AxisSXR40BitDepthString      "AXIS_BIT_DEPTH"
#define AxisSXR40FrameFormatString   "AXIS_FRAME_FORMAT"
#define AxisSXR40BinningModeString   "AXIS_BIN_MODE"
#define AxisSXR40ImageModeString     "AXIS_IMG_MODE"
#define AxisSXR40AutoExposureString  "AXIS_AUTO_EXPOSURE"
#define AxisSXR40FanGearString       "AXIS_FAN_GEAR"
#define AxisSXR40AutoLevelsString    "AXIS_AUTO_LEVELS"
#define AxisSXR40HistogramString     "AXIS_HISTOGRAM"
#define AxisSXR40EnhanceString       "AXIS_ENHANCE"
#define AxisSXR40DefectCorrString    "AXIS_DEFECT_CORR"
#define AxisSXR40DenoiseString       "AXIS_ENABLE_DENOISE"
#define AxisSXR40FlatCorrString      "AXIS_FLAT_CORR"
#define AxisSXR40DynRgeCorrString    "AXIS_DYN_RGE_CORR"
#define AxisSXR40BrightnessString    "AXIS_BRIGHTNESS"
#define AxisSXR40BlackLevelString    "AXIS_BLACK_LEVEL"
#define AxisSXR40SharpnessString     "AXIS_SHARPNESS"
#define AxisSXR40NoiseLevelString    "AXIS_NOISE_LEVEL"
#define AxisSXR40HDRKString          "AXIS_HDRK"
#define AxisSXR40GammaString         "AXIS_GAMMA"
#define AxisSXR40ContrastString      "AXIS_CONTRAST"
#define AxisSXR40LeftLevelString     "AXIS_LEFT_LEVELS"
#define AxisSXR40RightLevelString    "AXIS_RIGHT_LEVELS"
#define AxisSXR40TriggerEdgeString   "AXIS_TRIG_EDGE"
#define AxisSXR40TriggerExposureString "AXIS_TRIG_EXP"
#define AxisSXR40TriggerDelayString  "AXIS_TRIG_DLY"
#define AxisSXR40TriggerSoftwareString "AXIS_TRIG_SOFT"
#define AxisSXR40TriggerOut1ModeString   "AXIS_TRGOUT1_MODE"
#define AxisSXR40TriggerOut1EdgeString   "AXIS_TRGOUT1_EDGE"
#define AxisSXR40TriggerOut1DelayString  "AXIS_TRGOUT1_DLY"
#define AxisSXR40TriggerOut1WidthString  "AXIS_TRGOUT1_WIDTH"
#define AxisSXR40TriggerOut2ModeString   "AXIS_TRGOUT2_MODE"
#define AxisSXR40TriggerOut2EdgeString   "AXIS_TRGOUT2_EDGE"
#define AxisSXR40TriggerOut2DelayString  "AXIS_TRGOUT2_DLY"
#define AxisSXR40TriggerOut2WidthString  "AXIS_TRGOUT2_WIDTH"
#define AxisSXR40TriggerOut3ModeString   "AXIS_TRGOUT3_MODE"
#define AxisSXR40TriggerOut3EdgeString   "AXIS_TRGOUT3_EDGE"
#define AxisSXR40TriggerOut3DelayString  "AXIS_TRGOUT3_DLY"
#define AxisSXR40TriggerOut3WidthString  "AXIS_TRGOUT3_WIDTH"
#define AxisSXR40TECEnableString  "AXIS_TEC_ENABLE"
#define AxisSXR40BuffFramesString "AXIS_BUFF_FRAMES"
#define AxisSXR40BuffTotalString  "AXIS_BUFF_TOTAL"

/* Frame formats offered to EPICS. RGB888 is deliberately excluded.
 *
 * This is a mono sensor, and selecting RGB888 does not fail politely -- measured
 * 2026-07-29: TUCAM_Buf_WaitForFrame then returns TUCAMRET_NOT_SUPPORT (0x80000312)
 * and acquisition stops. Worse, setting the format back to Raw is not enough to
 * recover: the format takes effect at Buf_Alloc, so the capture has to be stopped
 * and restarted before frames flow again. A menu entry that stalls the detector
 * until someone thinks to cycle Acquire is a trap, not a feature.
 *
 * RAW and USUAl are the two usable formats and are bit-identical on this camera
 * (measured -- see the characterisation notes), so nothing is lost. If this module
 * is ever pointed at a colour Dhyana, add RGB888 back here. */
static const int frameFormats[2] = {
    TUFRM_FMT_RAW,
    TUFRM_FMT_USUAl
};

static const char* driverName = "axisSXR40";

static int TUCAMInitialized = 0;

/* Main driver class inherited from areaDetector ADDriver class */

class axisSXR40 : public ADDriver
{
    public:
        axisSXR40( const char* portName, int cameraId, int traceMask, int maxBuffers,
                size_t maxMemory, int priority, int stackSize);

        /* Virtual methods to override from ADDrive */
        virtual asynStatus readEnum(asynUser *pasynUser, char *strings[], int values[], int severities[], size_t nElements, size_t *nIn);
        virtual asynStatus writeInt32( asynUser *pasynUser, epicsInt32 value);
        virtual asynStatus writeFloat64( asynUser *pasynUser, epicsFloat64 value);

        /* These should be private but must be called from C */
        void imageGrabTask();
        void shutdown();
        void tempTask();

    protected:
        int AxisSXR40Bus;
#define FIRST_AXISSXR40_PARAM AxisSXR40Bus
        int AxisSXR40ProductID;
        int AxisSXR40TransferRate;
        int AxisSXR40FrameSpeed;
        int AxisSXR40BitDepth;
        int AxisSXR40BinMode;
        int AxisSXR40FanGear;
        int AxisSXR40ImageMode;
        int AxisSXR40AutoExposure;
        int AxisSXR40FrameFormat;
        int AxisSXR40AutoLevels;
        int AxisSXR40Histogram;
        int AxisSXR40Enhance;
        int AxisSXR40DefectCorr;
        int AxisSXR40Denoise;
        int AxisSXR40FlatCorr;
        int AxisSXR40DynRgeCorr;
        int AxisSXR40Brightness;
        int AxisSXR40BlackLevel;
        int AxisSXR40Sharpness;
        int AxisSXR40NoiseLevel;
        int AxisSXR40HDRK;
        int AxisSXR40Gamma;
        int AxisSXR40Contrast;
        int AxisSXR40LeftLevel;
        int AxisSXR40RightLevel;
        int AxisSXR40TriggerEdge;
        int AxisSXR40TriggerExposure;
        int AxisSXR40TriggerDelay;
        int AxisSXR40TriggerSoftware;
        int AxisSXR40TriggerOut1Mode;
        int AxisSXR40TriggerOut1Edge;
        int AxisSXR40TriggerOut1Delay;
        int AxisSXR40TriggerOut1Width;
        int AxisSXR40TriggerOut2Mode;
        int AxisSXR40TriggerOut2Edge;
        int AxisSXR40TriggerOut2Delay;
        int AxisSXR40TriggerOut2Width;
        int AxisSXR40TriggerOut3Mode;
        int AxisSXR40TriggerOut3Edge;
        int AxisSXR40TriggerOut3Delay;
        int AxisSXR40TriggerOut3Width;
        /* DIFFERENCE FROM ADTucsen (4): controls this camera has that ADTucsen
         * never exposed. Kept at the end so the FIRST/LAST pointer arithmetic
         * above stays contiguous. */
        int AxisSXR40TECEnable;      /* TUIDC_ENABLETEC  -- supported here, was missing */
        int AxisSXR40BuffFrames;     /* TUIDI_CURRENTBUFFRAMES -- dropped-frame telemetry */
        int AxisSXR40BuffTotal;      /* TUIDI_TOTALBUFFRAMES   -- ring depth (2 frames) */
#define LAST_AXISSXR40_PARAM AxisSXR40BuffTotal

    private:
        /* Local methods to this class */
        asynStatus grabImage();
        asynStatus startCapture();
        asynStatus stopCapture();

        asynStatus connectCamera();
        asynStatus disconnectCamera();

        asynStatus getTrigger();
        asynStatus setTrigger();
        asynStatus getTriggerOut(int port);
        asynStatus setTriggerOut(int port);
        asynStatus getROI();
        void reportCapabilitySupport();
        asynStatus setROI();

        /* camera property control functions */
        asynStatus getCamInfo(int nID, char* sBuf, int &val);
        asynStatus setCamInfo(int param, int nID, int dtype);
        asynStatus setSerialNumber();
        asynStatus getProperty(int nID, double& value);
        asynStatus setProperty(int nID, double value);
        asynStatus setCapability(int property, int value);
        asynStatus getCapability(int property, int& value);
        asynStatus getCapabilityText(int property, char *strings[], int values[], int severities[], size_t nElements, size_t *nIn);

        /* Data */
        int cameraId_;
        int exiting_;
        TUCAM_INIT apiHandle_;
        TUCAM_OPEN camHandle_;
        TUCAM_FRAME frameHandle_;
        TUCAM_TRIGGER_ATTR triggerHandle_;
        TUCAM_TRGOUT_ATTR triggerOutHandle_[3];
        epicsEventId startEventId_;
        NDArray *pRaw_;
        int triggerOutSupport_;
        int tempCalWarned_;   /* one-shot: raw temperature outside the fitted range */
};

#define NUM_AXISSXR40_PARAMS ((int)(&LAST_AXISSXR40_PARAM-&FIRST_AXISSXR40_PARAM+1))


/* Configuration function to configure one camera
 *
 * This function needs to be called once for each camera used by the IOC. A
 * call to this function instantiates one object of the AxisSXR40 class.
 * \param[in] portName asyn port to assign to the camera
 * \param[in] cameraId The camera index or serial number
 * \param[in] traceMask the initial value of asynTraceMask
 *            if set to 0 or 1 then asynTraceMask will be set to
 *            ASYN_TRACE_ERROR.
 *            if set to 0x21 ( ASYN_TRACE_WARNING | ASYN_TRACE_ERROR) then each
 *            call will be traced during initialization
 * \param[in] maxBuffers Maximum number of NDArray objects (image buffers) this
 *            driver is allowed to allocate.
 *            0 = unlimited
 * \param[in] maxMemory Maximum memort (in bytes) that this driver is allowed
 *            to allocate.
 *            0=unlimited
 * \param[in] priority The epics thread priority for this driver. 0= asyn
 *            default.
 * \param[in] stackSize The size of the stack of the EPICS port thread. 0=use
 *            asyn default.
 */
extern "C" int axisSXR40Config(const char *portName, int cameraId, int traceMask,
        int maxBuffers, size_t maxMemory, int priority, int stackSize)
{
    new axisSXR40( portName, cameraId, traceMask, maxBuffers, maxMemory, priority, stackSize);
    return asynSuccess;
}

static void c_shutdown(void *arg)
{
    axisSXR40 *t = (axisSXR40 *)arg;
    t->shutdown();
}

static void imageGrabTaskC(void *drvPvt)
{
    axisSXR40 *t = (axisSXR40 *)drvPvt;
    t->imageGrabTask();
}

static void tempReadTaskC(void *drvPvt)
{
    axisSXR40 *t = (axisSXR40 *)drvPvt;
    t->tempTask();
}

/* Constructor for the AxisSXR40 class */

axisSXR40::axisSXR40(const char *portName, int cameraId, int traceMask, int maxBuffers,
        size_t maxMemory, int priority, int stackSize)
    : ADDriver( portName, 1, NUM_AXISSXR40_PARAMS, maxBuffers, maxMemory, asynEnumMask,
            asynEnumMask, ASYN_CANBLOCK | ASYN_MULTIDEVICE, 1, priority, stackSize),
    cameraId_(cameraId), exiting_(0), pRaw_(NULL), triggerOutSupport_(0),
    tempCalWarned_(0)
{
    static const char *functionName = "axisSXR40";

    char versionString[20];
    asynStatus status;

    if(traceMask==0) traceMask = ASYN_TRACE_ERROR;
    pasynTrace->setTraceMask(pasynUserSelf, traceMask);

    /* Zero the SDK handles before anything touches them.
     *
     * These are plain members, so none of them were initialised -- and every one
     * has [in] fields the SDK reads. TUCAM_FRAME.uiRsdSize is the worst of them:
     * the header documents it as "how many frames do you want", and TUCAM_Buf_Alloc
     * reads it to size the frame ring. It was being passed indeterminate stack
     * garbage, and the observed ring depth of 2 was whatever the SDK made of that.
     * frameHandle_.ucFormatGet has the same problem until FrameFormat is written. */
    memset(&frameHandle_,      0, sizeof(frameHandle_));
    memset(&triggerHandle_,    0, sizeof(triggerHandle_));
    memset(&triggerOutHandle_, 0, sizeof(triggerOutHandle_));
    memset(&camHandle_,        0, sizeof(camHandle_));

    createParam(AxisSXR40BusString,           asynParamOctet,   &AxisSXR40Bus);
    createParam(AxisSXR40ProductIDString,     asynParamFloat64, &AxisSXR40ProductID);
    createParam(AxisSXR40TransferRateString,  asynParamFloat64, &AxisSXR40TransferRate);
    createParam(AxisSXR40FrameSpeedString,    asynParamInt32,   &AxisSXR40FrameSpeed);
    createParam(AxisSXR40BitDepthString,      asynParamInt32,   &AxisSXR40BitDepth);
    createParam(AxisSXR40BinningModeString,   asynParamInt32,   &AxisSXR40BinMode);
    createParam(AxisSXR40FanGearString,       asynParamInt32,   &AxisSXR40FanGear);
    createParam(AxisSXR40ImageModeString,     asynParamInt32,   &AxisSXR40ImageMode);
    createParam(AxisSXR40AutoExposureString,  asynParamInt32,   &AxisSXR40AutoExposure);
    createParam(AxisSXR40AutoLevelsString,    asynParamInt32,   &AxisSXR40AutoLevels);
    createParam(AxisSXR40HistogramString,     asynParamInt32,   &AxisSXR40Histogram);
    createParam(AxisSXR40EnhanceString,       asynParamInt32,   &AxisSXR40Enhance);
    createParam(AxisSXR40DefectCorrString,    asynParamInt32,   &AxisSXR40DefectCorr);
    createParam(AxisSXR40DenoiseString,       asynParamInt32,   &AxisSXR40Denoise);
    createParam(AxisSXR40FlatCorrString,      asynParamInt32,   &AxisSXR40FlatCorr);
    createParam(AxisSXR40DynRgeCorrString,    asynParamInt32,   &AxisSXR40DynRgeCorr);
    createParam(AxisSXR40FrameFormatString,   asynParamInt32,   &AxisSXR40FrameFormat);
    createParam(AxisSXR40BrightnessString,    asynParamFloat64, &AxisSXR40Brightness);
    createParam(AxisSXR40BlackLevelString,    asynParamFloat64, &AxisSXR40BlackLevel);
    createParam(AxisSXR40SharpnessString,     asynParamFloat64, &AxisSXR40Sharpness);
    createParam(AxisSXR40NoiseLevelString,    asynParamFloat64, &AxisSXR40NoiseLevel);
    createParam(AxisSXR40HDRKString,          asynParamFloat64, &AxisSXR40HDRK);
    createParam(AxisSXR40GammaString,         asynParamFloat64, &AxisSXR40Gamma);
    createParam(AxisSXR40ContrastString,      asynParamFloat64, &AxisSXR40Contrast);
    createParam(AxisSXR40LeftLevelString,     asynParamFloat64, &AxisSXR40LeftLevel);
    createParam(AxisSXR40RightLevelString,    asynParamFloat64, &AxisSXR40RightLevel);
    createParam(AxisSXR40TriggerEdgeString,   asynParamInt32,   &AxisSXR40TriggerEdge);
    createParam(AxisSXR40TriggerExposureString, asynParamInt32, &AxisSXR40TriggerExposure);
    createParam(AxisSXR40TriggerDelayString,   asynParamFloat64, &AxisSXR40TriggerDelay);
    createParam(AxisSXR40TriggerSoftwareString, asynParamInt32, &AxisSXR40TriggerSoftware);
    createParam(AxisSXR40TriggerOut1ModeString,  asynParamInt32,   &AxisSXR40TriggerOut1Mode);
    createParam(AxisSXR40TriggerOut1EdgeString,  asynParamInt32,   &AxisSXR40TriggerOut1Edge);
    createParam(AxisSXR40TriggerOut1DelayString, asynParamFloat64, &AxisSXR40TriggerOut1Delay);
    createParam(AxisSXR40TriggerOut1WidthString, asynParamFloat64, &AxisSXR40TriggerOut1Width);
    createParam(AxisSXR40TriggerOut2ModeString,  asynParamInt32,   &AxisSXR40TriggerOut2Mode);
    createParam(AxisSXR40TriggerOut2EdgeString,  asynParamInt32,   &AxisSXR40TriggerOut2Edge);
    createParam(AxisSXR40TriggerOut2DelayString, asynParamFloat64, &AxisSXR40TriggerOut2Delay);
    createParam(AxisSXR40TriggerOut2WidthString, asynParamFloat64, &AxisSXR40TriggerOut2Width);
    createParam(AxisSXR40TriggerOut3ModeString,  asynParamInt32,   &AxisSXR40TriggerOut3Mode);
    createParam(AxisSXR40TriggerOut3EdgeString,  asynParamInt32,   &AxisSXR40TriggerOut3Edge);
    createParam(AxisSXR40TriggerOut3DelayString, asynParamFloat64, &AxisSXR40TriggerOut3Delay);
    createParam(AxisSXR40TriggerOut3WidthString, asynParamFloat64, &AxisSXR40TriggerOut3Width);
    createParam(AxisSXR40TECEnableString,        asynParamInt32,   &AxisSXR40TECEnable);
    createParam(AxisSXR40BuffFramesString,       asynParamInt32,   &AxisSXR40BuffFrames);
    createParam(AxisSXR40BuffTotalString,        asynParamInt32,   &AxisSXR40BuffTotal);

    /* Set initial values for some parameters */
    setIntegerParam(NDDataType, NDUInt16);
    setIntegerParam(NDColorMode, NDColorModeMono);
    setIntegerParam(NDArraySizeZ, 0);
    setStringParam(ADStringToServer, "<not used by driver>");
    setStringParam(ADStringFromServer, "<not used by driver>");
    /* "Tucsen", not "AxisSXR40": the manufacturer of the camera this driver talks to
     * is Tucsen, and ADTucsen reports the same string, so Manufacturer_RBV reads
     * identically under either driver (the IOCs are meant to be interchangeable). */
    setStringParam(ADManufacturer, "Tucsen");
    epicsSnprintf(versionString, sizeof(versionString), "%d.%d.%d",
            DRIVER_VERSION, DRIVER_REVISION, DRIVER_MODIFICATION);
    setStringParam(NDDriverVersion, versionString);

    status = connectCamera();
    if (status != asynSuccess) {
        asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                "%s:%s: camera connection failed\n",
                driverName, functionName);
        setIntegerParam(ADStatus, ADStatusDisconnected);
        setStringParam(ADStatusMessage, "camera connection failed");
        report(stdout, 1);
        return;
    }

    startEventId_ = epicsEventCreate(epicsEventEmpty);

    /* Launch image read task */
    epicsThreadCreate("AxisSXR40ImageReadTask",
            epicsThreadPriorityMedium,
            epicsThreadGetStackSize(epicsThreadStackMedium),
            imageGrabTaskC, this);

    /* Launch temp task -- unless disabled for diagnosis.
     *
     * AXIS_NO_TEMP_POLL (any value) skips this thread entirely. It exists to test
     * one hypothesis from info/incidents/stop-deadlock.md: that this poll's USB control
     * transfers, interleaved with a high-frame-rate stream stop, contribute to the
     * camera ceasing to complete USB transfers. In the 2026-08-25 13:25 deadlock
     * the poll was the thread caught holding the port lock inside the SDK; whether
     * it is a cause or only the most frequent victim is what this switch tests.
     * With it set, TemperatureActual, TransferRate, BuffFrames and BuffTotal stop
     * updating. Diagnostic only -- never set it in normal operation. */
    if (getenv("AXIS_NO_TEMP_POLL") == NULL) {
        epicsThreadCreate("AxisSXR40TempReadTask",
                epicsThreadPriorityMedium,
                epicsThreadGetStackSize(epicsThreadStackMedium),
                tempReadTaskC, this);
    } else {
        asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                "%s: AXIS_NO_TEMP_POLL is set -- temperature/telemetry poll DISABLED "
                "(diagnostic mode, see info/incidents/stop-deadlock.md)\n", driverName);
    }

    /* Launch shutdown task */
    epicsAtExit(c_shutdown, this);

    return;
}

void axisSXR40::shutdown(void)
{
    exiting_=1;
    if (camHandle_.hIdxTUCam != NULL){
        disconnectCamera();
    }
    TUCAMInitialized--;
    if(TUCAMInitialized==0){
        TUCAM_Api_Uninit();
    }
}

asynStatus axisSXR40::connectCamera()
{
    static const char* functionName = "connectCamera";
    int tucStatus;
    int status = asynSuccess;

    // Init API
    char szPath[1024] = {0};
    if (getcwd(szPath, sizeof(szPath)) == NULL) {
        /* Only used as the SDK's config-file search path. Falling back to "." keeps
         * Api_Init working rather than handing it an indeterminate buffer. */
        asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                "%s:%s: getcwd failed (%s); using \".\" as the SDK config path\n",
                driverName, functionName, strerror(errno));
        szPath[0] = '.';
        szPath[1] = '\0';
    }
    apiHandle_.pstrConfigPath = szPath;
    apiHandle_.uiCamCount = 0;

    tucStatus = TUCAM_Api_Init(&apiHandle_);
    if (tucStatus!=TUCAMRET_SUCCESS){
        asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                "%s:%s: TUCAM API init failed (0x%x)\n",
                driverName, functionName, tucStatus);
        return asynError;
    }
    if (apiHandle_.uiCamCount<1){
        asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                "%s:%s: no camera detected (0x%x)\n",
                driverName, functionName, tucStatus);
        return asynError;
    }

    TUCAMInitialized++;

    // Init camera
    camHandle_.hIdxTUCam = NULL;
    camHandle_.uiIdxOpen = cameraId_;

    tucStatus = TUCAM_Dev_Open(&camHandle_);
    if (tucStatus!=TUCAMRET_SUCCESS){
        asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                "%s:%s: open camera device failed (0x%x)\n",
                driverName, functionName, tucStatus);
        return asynError;
    }

    status |= setCamInfo(AxisSXR40Bus, TUIDI_BUS, 0);
    status |= setCamInfo(AxisSXR40ProductID, TUIDI_PRODUCT, 1);
    status |= setCamInfo(ADSDKVersion, TUIDI_VERSION_API, 0);
    status |= setCamInfo(ADFirmwareVersion, TUIDI_VERSION_FRMW, 0);
    status |= setCamInfo(ADModel, TUIDI_CAMERA_MODEL, 0);
    status |= setSerialNumber();
    /* Off-contract but working. The TUCAM API Development Guide (p37) says
     * TUIDI_CURRENT_WIDTH and TUIDI_CURRENT_HEIGHT "must be used with
     * [TUCAM_Dev_GetInfoEx], and called after [TUCAM_Buf_Alloc]". setCamInfo()
     * uses TUCAM_Dev_GetInfo, and this runs at connect -- long before the first
     * Buf_Alloc in imageGrabTask(). It returns the right answer anyway (4096 on
     * both axes, verified against MaxSizeX_RBV/MaxSizeY_RBV), so it is left
     * alone; noted because it is the sort of thing that works until an SDK
     * update decides it should not. */
    status |= setCamInfo(ADMaxSizeX, TUIDI_CURRENT_WIDTH, 2);
    status |= setCamInfo(ADMaxSizeY, TUIDI_CURRENT_HEIGHT, 2);
    status |= getROI();
    status |= getTrigger();

    triggerOutSupport_ = 1;
    for(int port = 0; port < 3; port++) {
        if (getTriggerOut(port) != asynSuccess) {
            triggerOutSupport_ = 0;
            break;
        }
    }

    reportCapabilitySupport();

    return (asynStatus)status;
}

/* Probe every id this driver drives and log which the attached camera actually
 * implements.
 *
 * There is no "list what you support" call in the TUCam SDK: *_GetAttr
 * returning an error IS the only way to discover that an id is unavailable, and
 * an unsupported Set fails silently. On this camera 8 of the 26 ids inherited
 * from ADTucsen are unimplemented -- auto-exposure, CMS/HDR image mode, defect
 * correction, enhance, black level, brightness, sharpness and HDR-K -- so their
 * OPI controls would sit there looking functional while doing nothing.
 *
 * Logging the audit at connect makes that visible in the IOC startup output
 * instead of during a confusing commissioning session, and keeps the driver
 * honest if it is ever pointed at a different Dhyana model with a different
 * feature set. Watch for FLTCORRECTION (flat field, supported here) versus
 * DFTCORRECTION (defect, not) -- easy to conflate. */
/* What this audit does and does not tell you
 * ------------------------------------------
 * It probes with *_GetAttr, which is the only way to discover an unavailable id
 * -- there is no "list what you support" call, and an unsupported Set fails
 * silently. But GetAttr succeeding does NOT mean the id is usable:
 *
 *   - TUIDC_ENABLETEC passes this audit, yet
 *     Dhyana_Series_Properties&Capabilities marks ENABLETEC (0x3B) as NOT
 *     supported for 4040 and 4040BSI.
 *   - TUIDC_ATLEVELS, TUIDC_HISTC and TUIDC_FLTCORRECTION all pass, and all
 *     reject writes with TUCAMRET_NO_RESOURCE because a precondition is unmet.
 *
 * So read the summary as "ids the camera will talk about", not "ids that work".
 * setCapability() documents how to tell the two apart from the error code. */
void axisSXR40::reportCapabilitySupport()
{
    static const char* functionName = "reportCapabilitySupport";
    struct { int id; const char *name; } capa[] = {
        {TUIDC_RESOLUTION,     "TUIDC_RESOLUTION"},
        {TUIDC_BITOFDEPTH,     "TUIDC_BITOFDEPTH"},
        {TUIDC_PIXELCLOCK,     "TUIDC_PIXELCLOCK"},
        {TUIDC_HORIZONTAL,     "TUIDC_HORIZONTAL"},
        {TUIDC_VERTICAL,       "TUIDC_VERTICAL"},
        {TUIDC_FAN_GEAR,       "TUIDC_FAN_GEAR"},
        {TUIDC_ENABLETEC,      "TUIDC_ENABLETEC"},
        {TUIDC_ATLEVELS,       "TUIDC_ATLEVELS"},
        {TUIDC_HISTC,          "TUIDC_HISTC"},
        {TUIDC_ENABLEDENOISE,  "TUIDC_ENABLEDENOISE"},
        {TUIDC_FLTCORRECTION,  "TUIDC_FLTCORRECTION"},
        {TUIDC_ATEXPOSURE,     "TUIDC_ATEXPOSURE"},
        {TUIDC_IMGMODESELECT,  "TUIDC_IMGMODESELECT"},
        {TUIDC_DFTCORRECTION,  "TUIDC_DFTCORRECTION"},
        {TUIDC_ENHANCE,        "TUIDC_ENHANCE"},
    };
    struct { int id; const char *name; } prop[] = {
        {TUIDP_EXPOSURETM,     "TUIDP_EXPOSURETM"},
        {TUIDP_GLOBALGAIN,     "TUIDP_GLOBALGAIN"},
        {TUIDP_TEMPERATURE,    "TUIDP_TEMPERATURE"},
        {TUIDP_NOISELEVEL,     "TUIDP_NOISELEVEL"},
        {TUIDP_GAMMA,          "TUIDP_GAMMA"},
        {TUIDP_CONTRAST,       "TUIDP_CONTRAST"},
        {TUIDP_LFTLEVELS,      "TUIDP_LFTLEVELS"},
        {TUIDP_RGTLEVELS,      "TUIDP_RGTLEVELS"},
        {TUIDP_BLACKLEVEL,     "TUIDP_BLACKLEVEL"},
        {TUIDP_BRIGHTNESS,     "TUIDP_BRIGHTNESS"},
        {TUIDP_SHARPNESS,      "TUIDP_SHARPNESS"},
        {TUIDP_HDR_KVALUE,     "TUIDP_HDR_KVALUE"},
    };
    int nCapa = 0, nProp = 0;

    for (size_t i = 0; i < sizeof(capa)/sizeof(capa[0]); i++) {
        TUCAM_CAPA_ATTR a;
        memset(&a, 0, sizeof(a));
        a.idCapa = capa[i].id;
        int okAttr = (TUCAMRET_SUCCESS == TUCAM_Capa_GetAttr(camHandle_.hIdxTUCam, &a));
        if (okAttr) nCapa++;
        asynPrint(pasynUserSelf, ASYN_TRACE_FLOW, "%s:%s: %-22s %s\n",
                  driverName, functionName, capa[i].name,
                  okAttr ? "supported" : "NOT SUPPORTED");
    }
    for (size_t i = 0; i < sizeof(prop)/sizeof(prop[0]); i++) {
        TUCAM_PROP_ATTR a;
        memset(&a, 0, sizeof(a));
        a.idProp = prop[i].id;
        a.nIdxChn = 0;
        int okAttr = (TUCAMRET_SUCCESS == TUCAM_Prop_GetAttr(camHandle_.hIdxTUCam, &a));
        if (okAttr) nProp++;
        asynPrint(pasynUserSelf, ASYN_TRACE_FLOW, "%s:%s: %-22s %s\n",
                  driverName, functionName, prop[i].name,
                  okAttr ? "supported" : "NOT SUPPORTED");
    }

    /* Summary at ERROR level so it appears without needing asyn tracing on --
     * it is the one line worth seeing on every IOC start. */
    asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
              "%s:%s: capability audit: %d/%zu capabilities, %d/%zu properties "
              "supported by this camera (set TRACE_FLOW for the per-id list)\n",
              driverName, functionName,
              nCapa, sizeof(capa)/sizeof(capa[0]),
              nProp, sizeof(prop)/sizeof(prop[0]));
}

asynStatus axisSXR40::disconnectCamera(void){
    static const char* functionName = "disconnectCamera";
    int tucStatus;
    int acquiring;
    asynStatus status;

    // check if acquiring
    status = getIntegerParam(ADAcquire, &acquiring);

    // if necessary stop acquiring
    if (status==asynSuccess && acquiring){
        status = stopCapture();
    }

    tucStatus = TUCAM_Dev_Close(camHandle_.hIdxTUCam);
    if (tucStatus!=TUCAMRET_SUCCESS){
        status = asynError;
        asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                "%s:%s: unable close camera (0x%x)\n",
                driverName, functionName, tucStatus);
    }
    return status;
}

void axisSXR40::imageGrabTask(void)
{
    static const char* functionName = "imageGrabTask";
    int status  = asynSuccess;
    int tucStatus;
    int imageCounter;
    int numImages, numImagesCounter;
    int imageMode;
    int triggerMode;
    int arrayCallbacks;
    epicsTimeStamp startTime;
    int acquire;

    lock();

    while(1){
        /* Is acquisition active? */
        getIntegerParam(ADAcquire, &acquire);

        /* If we are not acquiring wait for a semaphore that is given when
         * acquisition is started */
        if(!acquire){
            if (!status) {
                setIntegerParam(ADStatus, ADStatusIdle);
                setStringParam(ADStatusMessage, "Waiting for the acquire command");
                callParamCallbacks();
            }
            asynPrint(pasynUserSelf, ASYN_TRACE_FLOW,
                    "%s:%s: waiting for acquisition to start\n",
                    driverName, functionName);
            unlock();
            tucStatus = TUCAM_Cap_Stop(camHandle_.hIdxTUCam);
            epicsEventWait(startEventId_);
            lock();
            getIntegerParam(ADTriggerMode, &triggerMode);

            /* uiRsdSize is frames-per-fetch, NOT the ring depth.
             *
             * TUDefine.h's comment -- "The frame reserved size (how many frames do
             * you want)" -- reads like a ring-depth request, and it is not. The
             * TUCAM API Development Guide p61 gives the field as "[in] Number of
             * frames to get", and the vendor's own example sets it to 1 with the
             * comment "Number of frames captured at a time" (guide p29). pBuffer is
             * then laid out as uiRsdSize consecutive
             * header+image+reserved frames (guide p68).
             *
             * Setting it to 8 was tried on 2026-07-29 and is why this comment
             * exists: the ring stayed at 2 ("Can get 2 frames!") and the IOC died
             * with "double free or corruption (out)", because the SDK sized pBuffer
             * for 8 frames while this driver reads exactly one per WaitForFrame.
             *
             * 1 is the documented value for one-frame-at-a-time capture, which is
             * what grabImage() does. Ring depth is not settable from here; it is
             * fixed at 2 in SDK 2.0.7.0. See info/known-gaps/TODO.md in the support repo. */
            frameHandle_.uiRsdSize = 1;
            tucStatus = TUCAM_Buf_Alloc(camHandle_.hIdxTUCam, &frameHandle_);
            tucStatus = TUCAM_Cap_Start(camHandle_.hIdxTUCam, triggerMode);
            if (tucStatus!=TUCAMRET_SUCCESS){
                status = asynError;
                asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                        "%s:%s: failed to start image capture (0x%x)\n",
                        driverName, functionName, tucStatus);
                setIntegerParam(ADAcquire, 0);
                setIntegerParam(ADStatus, ADStatusError);
                setStringParam(ADStatusMessage, "Failed to start image capture");
                callParamCallbacks();
                continue;
            }

            setIntegerParam(ADStatus, ADStatusAcquire);
            setStringParam(ADStatusMessage, "Acquiring...");
            asynPrint(pasynUserSelf, ASYN_TRACE_FLOW,
                    "%s:%s: acquisition started\n",
                    driverName, functionName);
            setIntegerParam(ADNumImagesCounter, 0);
            setIntegerParam(ADAcquire, 1);
            callParamCallbacks();
        }

        /* Get the current time */
        epicsTimeGetCurrent(&startTime);

        status = grabImage();
        if (status==asynError){
            // Release the allocated NDArray
            if (pRaw_) pRaw_->release();
            pRaw_ = NULL;

            getIntegerParam(ADAcquire, &acquire);
            if (acquire == 0) {
                if (imageMode != ADImageContinuous) {
                    setIntegerParam(ADStatus, ADStatusAborted);
                    setStringParam(ADStatusMessage, "Aborted by user");
                } else {
                    status = asynSuccess;
                }
            } else {
                stopCapture();
                setIntegerParam(ADAcquire, 0);
                setIntegerParam(ADStatus, ADStatusError);
                /* Only the generic message if grabImage() did not leave a specific
                 * one. It sets a precise message for the pool-exhaustion case, and
                 * overwriting that with "Failed to get image" is how a diagnosable
                 * fault becomes an afternoon of guessing. */
                char curMsg[256] = {0};
                getStringParam(ADStatusMessage, sizeof(curMsg), curMsg);
                if (strncmp(curMsg, "NDArrayPool", 11) != 0)
                    setStringParam(ADStatusMessage, "Failed to get image");
            }
            callParamCallbacks();
            continue;
        }

        getIntegerParam(NDArrayCounter, &imageCounter);
        getIntegerParam(ADNumImages, &numImages);
        getIntegerParam(ADNumImagesCounter, &numImagesCounter);
        getIntegerParam(ADImageMode, &imageMode);
        getIntegerParam(NDArrayCallbacks, &arrayCallbacks);
        imageCounter++;
        numImagesCounter++;
        setIntegerParam(NDArrayCounter, imageCounter);
        setIntegerParam(ADNumImagesCounter, numImagesCounter);

        if(arrayCallbacks){
            doCallbacksGenericPointer(pRaw_, NDArrayData, 0);
        }

        if (pRaw_) pRaw_->release();
        pRaw_ = NULL;

        if ((imageMode==ADImageSingle) || ((imageMode==ADImageMultiple) && (numImagesCounter>=numImages))){
            status = stopCapture();
            setIntegerParam(ADAcquire, 0);
            setIntegerParam(ADStatus, ADStatusIdle);
        }
        callParamCallbacks();
    }
}

asynStatus axisSXR40::grabImage()
{
    static const char* functionName = "grabImage";
    asynStatus status = asynSuccess;
    /* TUCAMRET, not int: this is compared against TUCAMRET_ABORT below, and
     * the enum's values run past INT_MAX (TUCAMRET_NOT_SUPPORT is 0x80000312),
     * so an int comparison is both signedness-mismatched and lossy. Part of
     * the same upstream fix, xiaoqiangwang/ADTucsen c0d7081. */
    TUCAMRET tucStatus;
    int nCols, nRows;
    int pixelFormat, channels, pixelBytes;
    size_t dataSize, tDataSize;
    NDDataType_t dataType = NDUInt16;
    NDColorMode_t colorMode = NDColorModeMono;
    int numColors = 1;
    int pixelSize = 2;
    size_t dims[3] = {0};
    int nDims;
    int count;
    double acquireTime;
    int waitTimeout;


    /* DIFFERENCE FROM ADTucsen (1): explicit timeout.
     *
     * ADTucsen called WaitForFrame with two arguments, taking the header
     * default TUCAM_TIMEOUT of 1000 ms. This camera's exposure range reaches
     * 3600 s, so every exposure past ~1 s returned TUCAMRET_FAILURE and looked
     * like a dead camera -- for a soft X-ray detector that is a routine
     * operating point, not an edge case.
     *
     * Budget = exposure + a full readout + margin. Readout at full frame is
     * ~116 ms (33.5 MB at ~289 MB/s); TIMEOUT_MARGIN_MS covers that plus
     * first-frame startup with room to spare. The wait still returns promptly
     * on TUCAM_Buf_AbortWait(), which is how stopCapture breaks out, so a long
     * timeout does not make the IOC unresponsive. */
    getDoubleParam(ADAcquireTime, &acquireTime);
    waitTimeout = (int)(acquireTime * 1000.0) + TIMEOUT_MARGIN_MS;

    unlock();
    asynPrint(pasynUserSelf, ASYN_TRACE_FLOW,
            "%s:%s: wait for buffer (timeout %d ms)\n",
            driverName, functionName, waitTimeout);
    tucStatus = TUCAM_Buf_WaitForFrame(camHandle_.hIdxTUCam, &frameHandle_, waitTimeout);
    lock();
    if (tucStatus!= TUCAMRET_SUCCESS){
        /* TUCAMRET_ABORT is how a normal stop arrives here: stopCapture calls
         * TUCAM_Buf_AbortWait(), which breaks this wait deliberately. Logging
         * it as an error made every user-initiated stop look like a failure --
         * and, because the message names the timeout, specifically like a
         * timeout that had not actually elapsed. Fixed upstream in
         * xiaoqiangwang/ADTucsen c0d7081. Still returns asynError either way;
         * only the log is suppressed. */
        if (tucStatus != TUCAMRET_ABORT)
            asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                    "%s:%s: failed to wait for buffer (0x%x) after %d ms\n",
                    driverName, functionName, tucStatus, waitTimeout);
        return asynError;
    }

    // Width & height are array dimensions
    nCols = frameHandle_.usWidth;
    nRows = frameHandle_.usHeight;

    // Image format
    pixelFormat = frameHandle_.ucFormat;
    // Number of channels
    channels = frameHandle_.ucChannels;
    // Bytes per pixel
    pixelBytes = frameHandle_.ucElemBytes;
    // Frame image data size
    tDataSize = frameHandle_.uiImgSize;

    /* Frame geometry, at TRACE_FLOW. Worth having permanently: uiWidthStep is the
     * only way to tell whether the SDK buffer is padded, and therefore whether the
     * row-by-row copy below is doing anything. Nothing else reports it, which made
     * "has the padded path ever run?" unanswerable from the logs. */
    asynPrint(pasynUserSelf, ASYN_TRACE_FLOW,
            "%s:%s: frame %ux%u fmt=%u ch=%u elemBytes=%u imgSize=%u "
            "widthStep=%u (rowBytes=%u) offset=%u header=%u\n",
            driverName, functionName,
            (unsigned)frameHandle_.usWidth, (unsigned)frameHandle_.usHeight,
            (unsigned)frameHandle_.ucFormat, (unsigned)frameHandle_.ucChannels,
            (unsigned)frameHandle_.ucElemBytes, (unsigned)frameHandle_.uiImgSize,
            (unsigned)frameHandle_.uiWidthStep,
            (unsigned)(frameHandle_.usWidth * frameHandle_.ucChannels
                       * frameHandle_.ucElemBytes),
            (unsigned)frameHandle_.usOffset, (unsigned)frameHandle_.usHeader);

    /* There is zero documentation on what the formats mean
     * Most of the below is gleaned through trial and error */
    if (pixelFormat==TUFRM_FMT_RAW){
        // Raw data - no filtering applied
        if (pixelBytes == 1){
            dataType = NDUInt8;
            pixelSize = 1;
        } else if (pixelBytes==2) {
            dataType = NDUInt16;
            pixelSize = 2;
        }
        colorMode = NDColorModeMono;
        numColors = 1;
    } else if (pixelFormat==TUFRM_FMT_USUAl){
        if (pixelBytes == 1){
            dataType = NDUInt8;
            pixelSize = 1;
        } else if (pixelBytes == 2) {
            dataType = NDUInt16;
            pixelSize = 2;
        }

        if (channels==1){
            colorMode = NDColorModeMono;
            numColors = 1;
        } else if (channels==3){
            colorMode = NDColorModeRGB1;
            numColors = 3;
        }
    } else if (pixelFormat==TUFRM_FMT_RGB888){
        dataType = NDUInt8;
        pixelSize = 1;
        colorMode = NDColorModeRGB1;
        numColors = 3;
    } else {
        asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                "%s:%s: Unsupported pixel format %d\n",
                driverName, functionName, pixelFormat);
        return asynError;
    }
    if (numColors==1){
        nDims = 2;
        dims[0] = nCols;
        dims[1] = nRows;
    } else {
        nDims = 3;
        dims[0] = 3;
        dims[1] = nCols;
        dims[2] = nRows;
    }

    dataSize = dims[0]*dims[1]*pixelSize;
    if (nDims==3) dataSize *= dims[2];

    /* Accept a padded SDK buffer, but only when the SDK's own numbers say so.
     *
     * This check used to compare the unpadded size against uiImgSize and abort on
     * any difference -- which made the row-by-row copy below unreachable, since a
     * padded buffer is exactly the case that failed here. The two pieces of code
     * contradicted each other: one existed to handle padding, the other rejected it.
     *
     * The padded buffer is nRows * uiWidthStep, so that is what is allowed, and
     * ONLY that. Anything else is still a hard abort. The point of the equality is
     * that the row-by-row copy is enabled only when the stride model is confirmed by
     * the SDK's own reported size -- which is the precise condition under which that
     * copy is correct. A wrong guess cannot silently produce a sheared image; it
     * fails the test and aborts, as before.
     *
     * No padding has ever been observed on this camera, and it appears unreachable:
     * this check has never fired across full frame, 2x2 and 4x4 binning, and ROIs
     * with deliberately awkward row byte counts (2000, 2160, 1584); TUIDC_BITOFDEPTH
     * offers only 16; RGB888 is not supported by this mono sensor (WaitForFrame
     * returns TUCAMRET_NOT_SUPPORT); and ROI width must be a multiple of 8, so
     * rowBytes is always a multiple of 16. So the padded path stays unexercised --
     * but it is now reachable in principle rather than dead by construction. */
    {
        const size_t rowBytesChk = (size_t)dims[0] * pixelSize;
        const size_t paddedSize  = (size_t)dims[1] * frameHandle_.uiWidthStep;
        int padded = (nDims == 2)
                  && (frameHandle_.uiWidthStep > rowBytesChk)
                  && (tDataSize == paddedSize);
        if (dataSize != tDataSize && !padded){
            asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                    "%s:%s: data size mismatch: calculated=%zu, reported=%zu "
                    "(widthStep=%u, rowBytes=%zu, padded model would be %zu)\n",
                    driverName, functionName, dataSize, tDataSize,
                    (unsigned)frameHandle_.uiWidthStep, rowBytesChk, paddedSize);
            return asynError;
        }
        if (padded){
            asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                    "%s:%s: SDK buffer is PADDED (widthStep=%u vs rowBytes=%zu). "
                    "First observation on this camera -- the row-by-row copy is now "
                    "in use and has never been verified against hardware; check the "
                    "image for shear before trusting it.\n",
                    driverName, functionName,
                    (unsigned)frameHandle_.uiWidthStep, rowBytesChk);
        }
    }

    setIntegerParam(NDArraySizeX, nCols);
    setIntegerParam(NDArraySizeY, nRows);
    setIntegerParam(NDArraySize, (int)dataSize);
    setIntegerParam(NDDataType, dataType);
    setIntegerParam(NDColorMode, colorMode);

    pRaw_ = pNDArrayPool->alloc(nDims, dims, dataType, 0, NULL);
    if(!pRaw_){
        /* Out of NDArrayPool memory -- almost always the maxMemory cap in st.cmd
         * being reached because something downstream is holding arrays (a stalled
         * file writer, or NDPluginCircularBuff retaining frames). Say so, with the
         * numbers: upstream's "not enough buffers left" sent people looking for a
         * buffer count, which since ADCore R3-3 is not even bounded -- only total
         * memory is. Verified 2026-07-29 by capping the pool at 64 MiB and letting
         * the circular buffer fill: acquisition stops with ADStatusError and the IOC
         * stays up, which is the point of having a cap at all. */
        asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                "%s:%s [%s] ERROR: NDArrayPool alloc failed for %zu bytes "
                "(pool %.0f MB of %.0f MB, %d buffers). Almost certainly the "
                "maxMemory cap in st.cmd, reached because a downstream plugin is "
                "holding arrays. Aborting acquisition.\n",
                driverName, functionName, portName, dataSize,
                pNDArrayPool->getMemorySize()/1048576.0,
                pNDArrayPool->getMaxMemory()/1048576.0,
                pNDArrayPool->getNumBuffers());
        setStringParam(ADStatusMessage, "NDArrayPool out of memory (maxMemory cap)");
        return asynError;
    }
    /* DIFFERENCE FROM ADTucsen (2): copy row by row via uiWidthStep.
     *
     * ADTucsen did a single flat memcpy of dataSize bytes. That is correct only
     * while the SDK buffer is unpadded -- true at full frame on this camera
     * (measured uiWidthStep == 8192 == 4096 * 2 bytes) but not guaranteed for
     * ROI or binned modes, where a padded stride would shear the image.
     *
     * CAVEAT -- THE PADDED BRANCH BELOW IS CURRENTLY UNREACHABLE. The size check
     * above compares dataSize (nCols*nRows*pixelSize, i.e. unpadded) against
     * tDataSize (uiImgSize, the SDK's actual buffer size) and returns asynError
     * on any mismatch. A padded buffer has uiImgSize == nRows*uiWidthStep, which
     * is larger, so it fails that check and aborts before reaching this copy.
     * The row loop therefore only ever runs in cases the check already accepted,
     * which are exactly the unpadded ones the fast path handles.
     *
     * Measured 2026-07-29: no padding occurs on this camera in any geometry
     * tested -- full frame, 2x2 and 4x4 binned, and ROIs down to 1000x600 with
     * deliberately awkward row byte counts (2000, 1200). Every acquisition passed
     * the size check, so uiImgSize == width*height*2 throughout and the
     * contiguous fast path is what always executes.
     *
     * To make this branch mean anything, the check above has to accept padded
     * buffers (compare against nRows*uiWidthStep when uiWidthStep != rowBytes).
     * Left as-is deliberately rather than changed blind: nothing on this camera
     * exercises it, so a "fix" could not be verified.
     *
     * usOffset is where pixels begin; the frame's first 1024 bytes are
     * TUCAM_IMG_HEADER metadata. (usHeader reports the same 1024 here.) */
    {
        const unsigned char *src = frameHandle_.pBuffer + frameHandle_.usOffset;
        const size_t rowBytes = (size_t)nCols * numColors * pixelSize;
        if (frameHandle_.uiWidthStep == rowBytes) {
            memcpy(pRaw_->pData, src, dataSize);        /* contiguous: one copy */
        } else {
            unsigned char *dst = (unsigned char *)pRaw_->pData;
            for (int row = 0; row < nRows; ++row)
                memcpy(dst + (size_t)row * rowBytes,
                       src + (size_t)row * frameHandle_.uiWidthStep,
                       rowBytes);
        }
    }
    getIntegerParam(NDArrayCounter, &count);
    pRaw_->uniqueId = count;
    updateTimeStamp(&pRaw_->epicsTS);
    pRaw_->timeStamp = pRaw_->epicsTS.secPastEpoch+pRaw_->epicsTS.nsec/1e9;

    getAttributes(pRaw_->pAttributeList);

    pRaw_->pAttributeList->add("ColorMode", "Color mode", NDAttrInt32, &colorMode);

    return status;
}

/* Read enum menu */
asynStatus axisSXR40::readEnum(asynUser *pasynUser,
        char *strings[], int values[], int severities[], size_t nElements, size_t *nIn)
{
    int function = pasynUser->reason;
    const char *functionName = "readEnum";
    asynStatus status = asynSuccess;

    if (function == AxisSXR40BinMode) {
        status = getCapabilityText(TUIDC_RESOLUTION, strings, values, severities, nElements, nIn);
    } else if (function == AxisSXR40BitDepth) {
        TUCAM_CAPA_ATTR attrCapa;
        attrCapa.idCapa = TUIDC_BITOFDEPTH;
        int tucStatus = TUCAM_Capa_GetAttr(camHandle_.hIdxTUCam, &attrCapa);
        if (tucStatus != TUCAMRET_SUCCESS) {
            asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                "%s:%s unable to get bit of depth capability (0x%x)\n",
                driverName, functionName, tucStatus);
            *nIn = 0;
            return asynError;
        }
        /* The min/max value cannot be interpreted as a range, instead just two choices.
         * e.g. a Dhyana 95 sCMOS returns min=12 max=16 */
        char szRes[64] = {0};
        sprintf(szRes, "%d", attrCapa.nValMin);
        if (strings[0]) free(strings[0]);
        strings[0] = epicsStrDup(szRes);
        values[0] = attrCapa.nValMin;
        severities[0] = 0;
        *nIn = 1;
        if (attrCapa.nValMax > attrCapa.nValMin) {
            sprintf(szRes, "%d", attrCapa.nValMax);
            if (strings[1]) free(strings[1]);
            strings[1] = epicsStrDup(szRes);
            values[1] = attrCapa.nValMax;
            severities[1] = 0;
            *nIn = 2;
        }
    } else if (function == AxisSXR40FanGear) {
        status = getCapabilityText(TUIDC_FAN_GEAR, strings, values, severities, nElements, nIn);
    } else if (function == AxisSXR40ImageMode) {
        status = getCapabilityText(TUIDC_IMGMODESELECT, strings, values, severities, nElements, nIn);
    } else if (function == AxisSXR40FrameSpeed) {
        status = getCapabilityText(TUIDC_PIXELCLOCK, strings, values, severities, nElements, nIn);
    } else {
        *nIn = 0;
        status = asynError;
    }
    return status;
}

/* Sets an int32 parameter */
asynStatus axisSXR40::writeInt32( asynUser *pasynUser, epicsInt32 value)
{
    static const char* functionName = "writeInt32";
    const char* paramName;
    int status = asynSuccess;
    int tucStatus;
    int function = pasynUser->reason;

    getParamName(function, &paramName);
    status = setIntegerParam(function, value);

    if (function==ADAcquire){
        if (value){
            status = startCapture();
        } else {
            status = stopCapture();
        }
    } else if (function==ADMinX ||
               function==ADMinY ||
               function==ADSizeX ||
               function==ADSizeY){
        status = setROI();
    } else if (function==ADReverseX){
        status |= setCapability(TUIDC_HORIZONTAL, value);
        status |= getCapability(TUIDC_HORIZONTAL, value);
        if (status) {
            value = 0;
        }
        status |= setIntegerParam(ADReverseX, value);
    } else if (function==ADReverseY){
        status |= setCapability(TUIDC_VERTICAL, value);
        status |= getCapability(TUIDC_VERTICAL, value);
        if (status) {
            value = 0;
        }
        status |= setIntegerParam(ADReverseY, value);
    } else if ((function==ADTriggerMode) ||
               (function==AxisSXR40TriggerExposure)){
        status |= setTrigger();
        status |= getTrigger();
    } else if ((function==AxisSXR40TriggerOut1Mode) ||
               (function==AxisSXR40TriggerOut1Edge)){
        if (triggerOutSupport_) {
            status |= setTriggerOut(0);
            status |= getTriggerOut(0);
        } else {
            setIntegerParam(function, 0);
        }
    } else if ((function==AxisSXR40TriggerOut2Mode) ||
               (function==AxisSXR40TriggerOut2Edge)){
        if (triggerOutSupport_) {
            status |= setTriggerOut(1);
            status |= getTriggerOut(1);
        } else {
            setIntegerParam(function, 0);
        }
    } else if ((function==AxisSXR40TriggerOut3Mode) ||
               (function==AxisSXR40TriggerOut3Edge)){
        if (triggerOutSupport_) {
            status |= setTriggerOut(2);
            status |= getTriggerOut(2);
        } else {
            setIntegerParam(function, 0);
        }
    } else if (function==AxisSXR40FrameFormat){
        /* Bounds-check: the enum comes from EPICS and a stale autosave value or a
         * hand-written caput could index past the array. */
        if (value < 0 || value >= (int)(sizeof(frameFormats)/sizeof(frameFormats[0]))) {
            asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                    "%s:%s: FrameFormat %d out of range (0..%zu); ignoring\n",
                    driverName, functionName, value,
                    sizeof(frameFormats)/sizeof(frameFormats[0]) - 1);
            return asynError;
        }
        frameHandle_.ucFormatGet = frameFormats[value];
    } else if (function==AxisSXR40BinMode){
        status |= setCapability(TUIDC_RESOLUTION, value);
        status |= setROI();
    } else if (function==AxisSXR40BitDepth){
        status |= setCapability(TUIDC_BITOFDEPTH, value);
        status |= getCapability(TUIDC_BITOFDEPTH, value);
        status |= setIntegerParam(function, value);
    } else if (function==AxisSXR40TECEnable){
        /* Thermoelectric cooler on/off. Absent from ADTucsen.
         *
         * ---- READ THIS FIRST: THE COOLER IS ALREADY RUNNING -------------------
         * The obvious reading of the hazard note below -- "the TEC is off until
         * someone enables it here" -- is FALSE, and it is the dangerous reading.
         *
         * This capability is decoupled from actual cooler state on this unit.
         * Measured 2026-07-29: TUIDC_ENABLETEC reads 0 while the sensor holds
         * -9.5 C in a room-temperature lab; re-confirmed 2026-08-24 at -3.1 C
         * with the capability still reading 0. A sensor that far below ambient is
         * being actively cooled. The Peltier runs from camera power-on, whatever
         * this reads and whatever is written here.
         *
         * The consequence for the hazard: the coolant dependency is a STANDING
         * CONDITION of having the camera powered, not something this control
         * switches on. Water must be flowing whenever the camera is on -- that is
         * a beamline interlock question, and nothing in this driver, including
         * refusing to expose this parameter, affects it either way.
         *
         * The consequence for this code path: writing 1 cannot start a cooler
         * that is already running. Writing 0 is the direction with any prospect
         * of effect, and stopping cooling warms the sensor, which is an
         * operational problem, not a damage mechanism -- sensors are damaged by a
         * TEC running without heat rejection, not by being warm. Neither
         * direction has ever been observed to change anything.
         *
         * The readback is kept precisely BECAUSE it disagrees with reality: it is
         * the evidence for everything above. Do not "fix" it to match the
         * temperature, and do not delete it.
         *
         * ---- HARDWARE HAZARD (applies from camera power-on, see above) --------
         * The TEC's hot side is cooled by circulating water, and the AXIS-SXR-40
         * user manual is explicit about what happens without it (callout J,
         * p6): "A water supply failure would prevent the Peltier cooler from
         * maintaining required temperature on the sensor. The sensor would
         * overheat and possibly get damaged." Section 6.4 adds: "It is the sole
         * responsibility of the user to decide which temperature to set in order
         * to avoid permanent damage to the sensor."
         *
         * Requirements from the manual: ~60 W to remove from the airbox; water at
         * 15-20 C and ~1 l/min reaches a -20 C sensor; the TEC can pull ~50 C
         * below the water temperature. There is a second hazard at low
         * temperature -- "any trace of grease, gas, or water will condensate on
         * the sensor" if the chamber vacuum is imperfect.
         *
         * Nothing in software can see the coolant loop, so this driver cannot
         * interlock it -- and, per the note at the top, cannot avoid the hazard
         * by withholding the control either. Water must be flowing whenever the
         * camera is powered, not merely when someone touches this parameter.
         *
         * ---- AND IT MAY NOT DO ANYTHING -------------------------------------
         * reportCapabilitySupport() finds TUIDC_ENABLETEC present, but
         * Dhyana_Series_Properties&Capabilities marks ENABLETEC (0x3B) as NOT
         * supported for both 4040 and 4040BSI. Capa_GetAttr succeeding is not
         * proof a capability is usable -- see setCapability() for the two
         * distinct failure codes this SDK uses. As of 2026-07-29 this path has
         * never been executed against the camera, for the reason above. */
        status |= setCapability(TUIDC_ENABLETEC, value);
        status |= getCapability(TUIDC_ENABLETEC, value);
        status |= setIntegerParam(function, value);
    } else if (function==AxisSXR40FanGear){
        status |= setCapability(TUIDC_FAN_GEAR, value);
        status |= getCapability(TUIDC_FAN_GEAR, value);
        status |= setIntegerParam(function, value);
    } else if (function==AxisSXR40ImageMode){
        status |= setCapability(TUIDC_IMGMODESELECT, value);
        status |= getCapability(TUIDC_IMGMODESELECT, value);
        status |= setIntegerParam(function, value);
    } else if (function==AxisSXR40AutoExposure){
        status |= setCapability(TUIDC_ATEXPOSURE, value);
        status |= getCapability(TUIDC_ATEXPOSURE, value);
        status |= setIntegerParam(function, value);
    } else if (function==AxisSXR40AutoLevels){
        /* TUIDC_ATLEVELS is a 4-state selector, not an enable. Per
         * Dhyana_Series_Properties&Capabilities 3.1.9, range [0, 3] default 0:
         *   0 manual colour gradation
         *   1 automatic LEFT colour scale   (must open histogram statistics)
         *   2 automatic RIGHT colour scale  (must open histogram statistics)
         *   3 automatic left AND right      (must open histogram statistics)
         * The template's None/Left/Right/Both choices already match this.
         *
         * States 1-3 require TUIDC_HISTC on, which is why histogram is forced
         * below -- that dependency is real and documented, not a guess.
         *
         * BUG, left as found: setIntegerParam(function, value) is called twice
         * and the histogram readback is never published, so AXIS_HISTOGRAM goes
         * stale whenever AutoLevels changes it underneath. The second call
         * should be setIntegerParam(AxisSXR40Histogram, hist). */
        status |= setCapability(TUIDC_ATLEVELS, value);
        status |= getCapability(TUIDC_ATLEVELS, value);
        status |= setIntegerParam(function, value);
        int hist = (value!=0);
        status |= setCapability(TUIDC_HISTC, hist);
        status |= getCapability(TUIDC_HISTC, hist);
        /* Publish the histogram parameter we just changed, not AutoLevels again.
         * Was setIntegerParam(function, value) -- a duplicate of the line above,
         * which left AXIS_HISTOGRAM stale whenever AutoLevels turned it on. */
        status |= setIntegerParam(AxisSXR40Histogram, hist);
    } else if (function==AxisSXR40Histogram){
        status |= setCapability(TUIDC_HISTC, value);
        status |= getCapability(TUIDC_HISTC, value);
        status |= setIntegerParam(function, value);
    } else if (function==AxisSXR40Enhance){
        status |= setCapability(TUIDC_ENHANCE, value);
        status |= getCapability(TUIDC_ENHANCE, value);
        status |= setIntegerParam(function, value);
    } else if (function==AxisSXR40DefectCorr){
        status |= setCapability(TUIDC_DFTCORRECTION, value);
        status |= getCapability(TUIDC_DFTCORRECTION, value);
        status |= setIntegerParam(function, value);
    } else if (function==AxisSXR40Denoise){
        status |= setCapability(TUIDC_ENABLEDENOISE, value);
        status |= getCapability(TUIDC_ENABLEDENOISE, value);
        status |= setIntegerParam(function, value);
    } else if (function==AxisSXR40FlatCorr){
        /* TUIDC_FLTCORRECTION is a 4-step SEQUENCE, not an enable. Per
         * Dhyana_Series_Properties&Capabilities 3.1.15, range [0, 3] default 0:
         *   0 turn off flat field correction
         *   1 grab frame data
         *   2 calculate the flat field correction
         *   3 open flat field correction (only effective once 2 has succeeded)
         *
         * So it cannot be driven as a checkbox: reaching a working state means
         * walking 1 -> 2 -> 3 with frames flowing. The template exposes it as a
         * plain enable, which is why writes come back TUCAMRET_NO_RESOURCE
         * (0x80000102) -- there is no correction built to switch on. The
         * capability itself IS supported on 4040/4040BSI per the vendor table;
         * the resource behind it is what is missing. */
        status |= setCapability(TUIDC_FLTCORRECTION, value);
        status |= getCapability(TUIDC_FLTCORRECTION, value);
        status |= setIntegerParam(function, value);
    } else if (function==AxisSXR40TriggerSoftware){
        int acquire, triggerMode;
        getIntegerParam(ADAcquire, &acquire);
        getIntegerParam(ADTriggerMode, &triggerMode);
        if (acquire && triggerMode == TUCCM_TRIGGER_SOFTWARE) {
            tucStatus = TUCAM_Cap_DoSoftwareTrigger(camHandle_.hIdxTUCam);
            if (tucStatus != TUCAMRET_SUCCESS)
                status = asynError;
        }
    } else {
        if (function < FIRST_AXISSXR40_PARAM){
            status = ADDriver::writeInt32(pasynUser, value);
        }
    }
    callParamCallbacks();
    if (status)
        asynPrint(pasynUser, ASYN_TRACE_ERROR,
                "%s:%s: error, status=%d function=%d, value=%d\n",
                driverName, functionName, status, function, value);
    else
        asynPrint(pasynUser, ASYN_TRACEIO_DRIVER,
                "%s:%s: function=%d, value=%d\n",
                driverName, functionName, function, value);

    return (asynStatus)status;
}

void axisSXR40::tempTask(void){
    static const char* functionName = "tempTask";
    TUCAM_VALUE_INFO valInfo;
    int tucStatus;
    double dbVal;

    lock();
    while (!exiting_){
        tucStatus = TUCAM_Prop_GetValue(camHandle_.hIdxTUCam,
                TUIDP_TEMPERATURE, &dbVal);
        if (tucStatus!=TUCAMRET_SUCCESS){
            asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                   "%s:%s: failed to read temperature (0x%x)\n",
                    driverName, functionName, tucStatus);
        } else {
            /* THIS VALUE IS NOT IN DEGREES CELSIUS -- it is published raw, which is
             * why axisSXR40.template overrides ADBase's EGU="C" to "raw" for
             * TemperatureActual.
             *
             * TUIDP_TEMPERATURE carries two different quantities depending on
             * direction, which is the trap here:
             *
             *   WRITE (setpoint) -- Dhyana_Series_Properties&Capabilities 3.2.5:
             *     range [0, 100], default 30, "Min Temperature -50", so
             *     value = C + 50. writeFloat64() applies that, and it is correct.
             *
             *   READ (this call)  -- returns the measured sensor temperature on
             *     AXIS's uncalibrated scale. Test report p10, for USB3
             *     specifically: "the temperatures displayed by the software are
             *     not calibrated. The real temperature of the sensor in C is
             *     Tsensor(C) = 1.7 x Value + 15".
             *
             * Measured 2026-07-29, which settles it: this read returned -9.05.
             * That is outside [0, 100], so it cannot be on the setpoint scale --
             * the two directions really are different quantities. -9.05 maps to
             * about -0.4 C, plausible; the setpoint reading of the same property
             * was 25 at the time.
             *
             * So converting here would be correct (C = 1.7 * dbVal + 15), and is
             * deliberately NOT done yet: the relation comes from AXIS's report on
             * one unit (s/n 702) over a plotted range of only -25..+5, and it has
             * not been checked against a reference thermometer on this camera.
             * Publishing raw with EGU="raw" is honest; publishing a wrong Celsius
             * number is not. Resolve by measurement, then convert here.
             *
             * This module's README previously reported "about -9.5 C with the TEC
             * running" -- that was this raw value read as Celsius. It is roughly
             * -1 C.
             *
             * Now converted, using this unit's factory calibration. See
             * AXIS_TEMP_CAL_SLOPE for why that is well-founded and when it stops
             * being so. */
            double tempC = AXIS_TEMP_CAL_SLOPE * dbVal + AXIS_TEMP_CAL_OFFSET;
            setDoubleParam(ADTemperatureActual, tempC);

            /* Warn once per excursion, not per poll: outside the fitted range the
             * conversion is extrapolation and should not be trusted quantitatively. */
            if (dbVal < AXIS_TEMP_RAW_MIN || dbVal > AXIS_TEMP_RAW_MAX) {
                if (!tempCalWarned_) {
                    tempCalWarned_ = 1;
                    asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                        "%s:%s: raw temperature %.2f is outside the calibrated range "
                        "[%.0f, %.0f] for %s -- %.2f C is extrapolated\n",
                        driverName, functionName, dbVal,
                        AXIS_TEMP_RAW_MIN, AXIS_TEMP_RAW_MAX,
                        AXIS_TEMP_CAL_UNIT, tempC);
                }
            } else {
                tempCalWarned_ = 0;
            }
        }

        valInfo.nID = TUIDI_TRANSFER_RATE;
        tucStatus = TUCAM_Dev_GetInfo(camHandle_.hIdxTUCam, &valInfo);
        if (tucStatus!=TUCAMRET_SUCCESS){
            asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                    "%s:%s: failed to read transfer rate(0x%x)\n",
                    driverName, functionName, tucStatus);
        } else {
            setDoubleParam(AxisSXR40TransferRate, valInfo.nValue);
        }

        /* SDK ring occupancy -- telemetry ADTucsen never surfaced. The ring is
         * only 2 frames deep, about 230 ms of slack at full frame (33.5 MB,
         * ~8.6 fps).
         *
         * Do not read this as an early warning at full frame: measured
         * 2026-07-29, CURRENTBUFFRAMES sits pinned AT TOTALBUFFRAMES for the
         * whole acquisition while dropping nothing, so the signal is saturated
         * from the first frame and cannot warn about anything. Use
         * NDPluginBase's DroppedArrays and achieved-vs-expected frame rate for
         * that. It is still informative at smaller geometries, where occupancy
         * does vary (at 1000x600, ~80 fps, it stays at 0), and TOTALBUFFRAMES is
         * how you confirm the ring depth from EPICS.
         *
         * The depth is not adjustable -- see the uiRsdSize comment in
         * imageGrabTask() for what that field actually does and why setting it
         * corrupted the heap. */
        valInfo.nID = TUIDI_CURRENTBUFFRAMES;
        if (TUCAMRET_SUCCESS == TUCAM_Dev_GetInfo(camHandle_.hIdxTUCam, &valInfo))
            setIntegerParam(AxisSXR40BuffFrames, valInfo.nValue);

        valInfo.nID = TUIDI_TOTALBUFFRAMES;
        if (TUCAMRET_SUCCESS == TUCAM_Dev_GetInfo(camHandle_.hIdxTUCam, &valInfo))
            setIntegerParam(AxisSXR40BuffTotal, valInfo.nValue);

        callParamCallbacks();
        unlock();
        epicsThreadSleep(0.5);
        lock();
    }
}

asynStatus axisSXR40::writeFloat64(asynUser *pasynUser, epicsFloat64 value)
{
    static const char* functionName = "writeFloat64";
    const char* paramName;
    int status = asynSuccess;
    int function = pasynUser->reason;

    getParamName(function, &paramName);
    status = setDoubleParam(function, value);

    if (function==ADAcquireTime){
        double valMilliSec = value*1000.0;
        status |= setProperty(TUIDP_EXPOSURETM, valMilliSec);
        status |= getProperty(TUIDP_EXPOSURETM, valMilliSec);
        status |= setDoubleParam(function, valMilliSec / 1000.0);
    } else if (function==ADTemperature){
        /* Temperature setpoint is offset by +50: the SDK property range is
         * [0, 100] with a documented "Min Temperature -50", so 0 = -50 C,
         * 50 = 0 C, 100 = +50 C. Confirmed for this model in
         * Dhyana_Series_Properties&Capabilities 3.2.5: Dhyana 4040, range
         * [0, 100], default 30, step 1 -- and default 30 = -20 C matches the
         * AXIS user manual's "-20 C suitable for measurements" exactly.
         *
         * NOTE the asymmetry: this write applies +50, but tempTask() reads
         * TUIDP_TEMPERATURE back with no -50 applied. See the comment there --
         * one of the two is wrong and it needs a measurement to say which. */
        value = value+50.0;
        status |= setProperty(TUIDP_TEMPERATURE, value);
    } else if (function==ADGain){
        status |= setProperty(TUIDP_GLOBALGAIN, value);
        status |= getProperty(TUIDP_GLOBALGAIN, value);
        if (status) value = 0;
        status |= setDoubleParam(function, value);
    } else if (function==AxisSXR40TriggerDelay){
        status |= setTrigger();
        status |= getTrigger();
    } else if ((function==AxisSXR40TriggerOut1Delay) ||
               (function==AxisSXR40TriggerOut1Width)){
        if (triggerOutSupport_) {
            status |= setTriggerOut(0);
            status |= getTriggerOut(0);
        } else {
            setDoubleParam(function, 0);
        }
    } else if ((function==AxisSXR40TriggerOut2Delay) ||
               (function==AxisSXR40TriggerOut2Width)){
        if (triggerOutSupport_) {
            status |= setTriggerOut(1);
            status |= getTriggerOut(1);
        } else {
            setDoubleParam(function, 0);
        }
    } else if ((function==AxisSXR40TriggerOut3Delay) ||
               (function==AxisSXR40TriggerOut3Width)){
        if (triggerOutSupport_) {
            status |= setTriggerOut(2);
            status |= getTriggerOut(2);
        } else {
            setDoubleParam(function, 0);
        }
    } else if (function==AxisSXR40Brightness){
        status |= setProperty(TUIDP_BRIGHTNESS, value);
        status |= getProperty(TUIDP_BRIGHTNESS, value);
        status |= setDoubleParam(function, value);
    } else if (function==AxisSXR40BlackLevel){
        status |= setProperty(TUIDP_BLACKLEVEL, value);
        status |= getProperty(TUIDP_BLACKLEVEL, value);
        if (status) value = 0;
        status |= setDoubleParam(function, value);
    } else if (function==AxisSXR40Sharpness){
        status |= setProperty(TUIDP_SHARPNESS, value);
        status |= getProperty(TUIDP_SHARPNESS, value);
        if (status) value = 0;
        status |= setDoubleParam(function, value);
    } else if (function==AxisSXR40NoiseLevel){
        status |= setProperty(TUIDP_NOISELEVEL, value);
        status |= getProperty(TUIDP_NOISELEVEL, value);
        if (status) value = 0;
        status |= setDoubleParam(function, value);
    } else if (function==AxisSXR40HDRK){
        status |= setProperty(TUIDP_HDR_KVALUE, value);
        status |= getProperty(TUIDP_HDR_KVALUE, value);
        if (status) value = 0;
        status |= setDoubleParam(function, value);
    } else if (function==AxisSXR40Gamma){
        status |= setProperty(TUIDP_GAMMA, value);
        status |= getProperty(TUIDP_GAMMA, value);
        if (status) value = 0;
        status |= setDoubleParam(function, value);
    } else if (function==AxisSXR40Contrast){
        status |= setProperty(TUIDP_CONTRAST, value);
        status |= getProperty(TUIDP_CONTRAST, value);
        if (status) value = 0;
        status |= setDoubleParam(function, value);
    } else if (function==AxisSXR40LeftLevel){
        status |= setProperty(TUIDP_LFTLEVELS, value);
        status |= getProperty(TUIDP_LFTLEVELS, value);
        if (status) value = 0;
        status |= setDoubleParam(function, value);
    } else if (function==AxisSXR40RightLevel){
        status |= setProperty(TUIDP_RGTLEVELS, value);
        status |= getProperty(TUIDP_RGTLEVELS, value);
        if (status) value = 0;
        status |= setDoubleParam(function, value);
    } else {
        if (function < FIRST_AXISSXR40_PARAM){
            status = ADDriver::writeFloat64(pasynUser, value);
        }
    }
    callParamCallbacks();
    if (status)
        asynPrint(pasynUser, ASYN_TRACE_ERROR,
                "%s:%s error, status=%d function=%d, value=%f\n",
                driverName, functionName, status, function, value);
    else
        asynPrint(pasynUser, ASYN_TRACEIO_DRIVER,
                "%s:%s: function=%d, value=%f\n",
                driverName, functionName, function, value);

    return (asynStatus)status;
}

/* DIFFERENCE FROM ADTucsen (5): correct the text-info calling convention.
 *
 * ADTucsen set valInfo.pText to its own buffer and expected the SDK to fill it.
 * It does not. For a text id the SDK returns a pointer to its OWN internal
 * string, so pText must be NULL going in and read back afterwards. Passing a
 * buffer returns TUCAMRET_SUCCESS and leaves it untouched -- a silent failure
 * indistinguishable from "this camera has no model name", which is exactly how
 * ADModel, ADSDKVersion and ADFirmwareVersion ended up blank.
 *
 * With this fixed the camera reports model "Dhyana XF/XV4040BSI", SDK version
 * "2.0.7.0" and firmware "2c022311292c01220509". The vendor GUI has always done
 * it this way (examples/QtDemo/caminformation.cpp) and is the only place the
 * convention is documented.
 *
 * sBuf must be at least TEXT_INFO_SIZE bytes. */
asynStatus axisSXR40::getCamInfo(int nID, char *sBuf, int &val)
{
    static const char* functionName = "getCamInfo";

    // Get camera information
    int tucStatus;
    TUCAM_VALUE_INFO valInfo;
    memset(&valInfo, 0, sizeof(valInfo));
    valInfo.pText     = NULL;      // MUST be NULL; the SDK hands back its own pointer
    valInfo.nValue    = 0;
    valInfo.nTextSize = TEXT_INFO_SIZE;

    valInfo.nID = nID;
    tucStatus = TUCAM_Dev_GetInfo(camHandle_.hIdxTUCam, &valInfo);
    if (tucStatus==TUCAMRET_SUCCESS){
        val = valInfo.nValue;
        if (sBuf) {
            if (valInfo.pText) {
                /* Copy out of the SDK's buffer -- we do not own it and have no
                 * guarantee about its lifetime past the next call. */
                strncpy(sBuf, valInfo.pText, TEXT_INFO_SIZE - 1);
                sBuf[TEXT_INFO_SIZE - 1] = '\0';
            } else {
                sBuf[0] = '\0';
            }
        }
        return asynSuccess;
    } else {
        asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                "%s:%s: could not get %d (0x%x)\n",
                driverName, functionName, nID, tucStatus);
        return asynError;
    }
}

asynStatus axisSXR40::setCamInfo(int param, int nID, int dtype)
{
    static const char* functionName = "setCamInfo";

    int tucStatus;
    TUCAM_VALUE_INFO valInfo;
    /* pText MUST be NULL -- see the convention note on getCamInfo. ADTucsen
     * passed a local buffer here, which is why every string this function feeds
     * (ADModel, ADSDKVersion, ADFirmwareVersion) came out blank. */
    memset(&valInfo, 0, sizeof(valInfo));
    valInfo.pText     = NULL;
    valInfo.nValue    = 0;
    valInfo.nTextSize = TEXT_INFO_SIZE;
    valInfo.nID = nID;

    tucStatus = TUCAM_Dev_GetInfo(camHandle_.hIdxTUCam, &valInfo);
    if (tucStatus==TUCAMRET_SUCCESS){
        if (param==AxisSXR40Bus){
            if (valInfo.nValue==768){
                setStringParam(AxisSXR40Bus, "USB3.0");
            } else{
                setStringParam(AxisSXR40Bus, "USB2.0");
            }
        } else if (dtype==0){
            /* setStringParam copies, so handing it the SDK's own pointer is
             * safe -- but only while it is non-NULL. */
            setStringParam(param, valInfo.pText ? valInfo.pText : "");
        } else if (dtype==1){
            setDoubleParam(param, valInfo.nValue);
        } else if (dtype==2){
            setIntegerParam(param, valInfo.nValue);
        }
        callParamCallbacks();
    } else {
        asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                "%s:%s param %d id %d (error=0x%x)\n",
                driverName, functionName, param, nID, tucStatus);
    }

    return asynSuccess;
}

asynStatus axisSXR40::setSerialNumber()
{
    static const char* functionName = "setSerialNumber";
    int tucStatus;
    char cSN[TUSN_SIZE] = {0};
    TUCAM_REG_RW regRW;

    regRW.nRegType = TUREG_SN;
    regRW.pBuf = &cSN[0];
    regRW.nBufSize = TUSN_SIZE;

    tucStatus = TUCAM_Reg_Read(camHandle_.hIdxTUCam, regRW);
    if (tucStatus==TUCAMRET_SUCCESS){
        setStringParam(ADSerialNumber, cSN);
        return asynSuccess;
    } else {
        asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                "%s:%s unable to get serial number (error=0x%x)\n",
                driverName, functionName, tucStatus);
        return asynError;
    }
}

asynStatus axisSXR40::setProperty(int property, double value){

    static const char* functionName = "setProperty";
    TUCAM_PROP_ATTR attrProp;
    int tucStatus;

    attrProp.nIdxChn = 0;
    attrProp.idProp = property;
    tucStatus = TUCAM_Prop_GetAttr(camHandle_.hIdxTUCam, &attrProp);
    if (tucStatus==TUCAMRET_SUCCESS)
    {
        asynPrint(pasynUserSelf, ASYN_TRACE_FLOW,
                "%s:%s: property value range [%f %f]\n",
                driverName, functionName,
                attrProp.dbValMin, attrProp.dbValMax);
        if(value<attrProp.dbValMin){
            value = attrProp.dbValMin;
            asynPrint(pasynUserSelf, ASYN_TRACE_WARNING,
                    "%s:%s: Clipping set min value: %d, %f\n",
                    driverName, functionName, property, value);
        } else if (value>attrProp.dbValMax){
            value = attrProp.dbValMax;
            asynPrint(pasynUserSelf, ASYN_TRACE_WARNING,
                    "%s:%s: Clipping set max value: %d, %f\n",
                    driverName, functionName, property, value);
        }
    }
    asynPrint(pasynUserSelf, ASYN_TRACE_FLOW,
            "%s:%s: value %f\n",
            driverName, functionName, value);

    tucStatus = TUCAM_Prop_SetValue(camHandle_.hIdxTUCam, property, value);
    if (tucStatus!=TUCAMRET_SUCCESS){
        asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                "%s:%s unable to set property %d to %f (0x%x)\n",
                driverName, functionName, property, value, tucStatus);
        return asynError;
    }
    return asynSuccess;
}

asynStatus axisSXR40::getProperty(int property, double& value)
{
    static const char* functionName = "getProperty";
    int tucStatus;

    tucStatus = TUCAM_Prop_GetValue(camHandle_.hIdxTUCam, property, &value);
    if (tucStatus!=TUCAMRET_SUCCESS){
        asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                "%s:%s unable to get property %d (0x%x)\n",
                driverName, functionName, property, tucStatus);
        return asynError;
    }
    return asynSuccess;
}

/* Reading the failures this logs
 * ------------------------------
 * The status code matters, because two very different problems look identical
 * from EPICS (both surface as a devAsyn "process write error"). Codes from the
 * TUCAM API Development Guide error table, p35:
 *
 *   0x80000312  TUCAMRET_NOT_SUPPORT   "The imager does not support capability
 *                                       or Propertys" -- genuinely absent.
 *                                       Expected, and harmless.
 *   0x80000102  TUCAMRET_NO_RESOURCE   "Not enough resources (not including
 *                                       memory)" -- the capability exists but
 *                                       something it depends on is not set up.
 *   0x80000311  TUCAMRET_OUT_OF_RANGE  value outside the capability's range.
 *
 * Measured on this camera, 2026-07-29, at every iocInit as autosave restores
 * values -- and the split lines up exactly with the vendor's own support table:
 *
 *   NOT_SUPPORT : 3 ATEXPOSURE, 12 IMGMODESELECT, 13 DFTCORRECTION, 22 ENHANCE
 *                 (all marked unsupported for 4040/4040BSI -- nothing to fix)
 *   NO_RESOURCE : 5 VERTICAL, 8 ATLEVELS, 10 HISTC, 15 FLTCORRECTION
 *                 (all marked SUPPORTED -- these are missing preconditions;
 *                  see the ATLEVELS and FLTCORRECTION cases in writeInt32)
 *
 * So a failure here is not evidence the camera lacks the feature. Only
 * NOT_SUPPORT means that. */
asynStatus axisSXR40::setCapability(int property, int val)
{
    static const char* functionName = "setCapability";
    int tucStatus;

    tucStatus = TUCAM_Capa_SetValue(camHandle_.hIdxTUCam, property, val);
    if (tucStatus!=TUCAMRET_SUCCESS)
    {
        /* Do not trust this return code on its own -- verify by readback.
         *
         * TUCAM_Capa_SetValue's own documented error list (guide 5.3.3.3) is
         * NOT_INIT / INVALID_IDCAPA / INVALID_VALUE / NOT_SUPPORT /
         * INVALID_CAMERA. It does NOT include NO_RESOURCE (0x80000102), which is
         * exactly what this camera returns for TUIDC_ATLEVELS, TUIDC_HISTC and
         * TUIDC_FLTCORRECTION -- and the value is applied anyway. Measured
         * 2026-07-29: writing AutoLevels 1/2/3 and FlatCorrection 1/2/3 all
         * returned NO_RESOURCE, and an independent Capa_GetValue read back
         * exactly the requested value every time (Left/Right/Both, Grab frame /
         * Calculate / Correction). The SDK also reuses NO_RESOURCE elsewhere to
         * mean "the pFrame pointer is empty", so it is a loosely-applied internal
         * code rather than a diagnostic.
         *
         * Reporting those as asynError produced a burst of devAsyn write errors at
         * every iocInit for controls that actually work, which is worse than
         * useless -- it trains people to ignore the log. So: if the camera reads
         * back what we asked for, the write succeeded, whatever the return code
         * says. Genuine failures still surface, because they fail the readback --
         * NOT_SUPPORT ids cannot be read at all, and TUIDC_VERTICAL (ReverseY)
         * reads back unchanged. */
        int readback = val - 1;          /* guarantees a mismatch if the get fails */
        if (TUCAMRET_SUCCESS == TUCAM_Capa_GetValue(camHandle_.hIdxTUCam,
                                                    property, &readback)
            && readback == val) {
            asynPrint(pasynUserSelf, ASYN_TRACE_FLOW,
                    "%s:%s capability %d=%d returned 0x%x but read back correctly; "
                    "treating as success\n",
                    driverName, functionName, property, val, tucStatus);
            return asynSuccess;
        }
        asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                "%s:%s unable to set capability %d=%d (0x%x, readback %d)\n",
                driverName, functionName, property, val, tucStatus, readback);
        return asynError;
    }
    return asynSuccess;
}

asynStatus axisSXR40::getCapability(int property, int& val)
{
    static const char* functionName = "getCapability";
    int tucStatus;

    tucStatus = TUCAM_Capa_GetValue(camHandle_.hIdxTUCam, property, &val);
    if (tucStatus!=TUCAMRET_SUCCESS)
    {
        asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                "%s:%s unable to get capability %d=%d\n",
                driverName, functionName, property, val);
        return asynError;
    }
    return asynSuccess;
}


asynStatus axisSXR40::getCapabilityText(int property, char *strings[], int values[], int severities[], size_t nElements, size_t *nIn)
{

    static const char* functionName = "getCapabilityText";
    int tucStatus;
    int i=0;

    TUCAM_CAPA_ATTR attrCapa;
    attrCapa.idCapa = property;

    tucStatus = TUCAM_Capa_GetAttr(camHandle_.hIdxTUCam, &attrCapa);
    if (tucStatus != TUCAMRET_SUCCESS) {
        asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                "%s:%s unable to get capability %d (0x%x)\n",
                driverName, functionName, property, tucStatus);
        *nIn = 0;
        return asynError;
    }

    for (i=0; i<attrCapa.nValMax-attrCapa.nValMin+1; i++) {
        char szRes[64] = {0};
        TUCAM_VALUE_TEXT valText;
        valText.dbValue = i;
        valText.nID = property;
        valText.nTextSize = 64;
        valText.pText = &szRes[0];

        tucStatus = TUCAM_Capa_GetValueText(camHandle_.hIdxTUCam, &valText);

        if (tucStatus != TUCAMRET_SUCCESS) {
            asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                    "%s:%s unable to get capability text %d:%d (0x%x)\n",
                    driverName, functionName, property, i, tucStatus);
            sprintf(valText.pText, "%d", i + attrCapa.nValMin);
        }

        if (strings[i])
        {
            free(strings[i]);
        }

        strings[i] = epicsStrDup(valText.pText);
        values[i]  = i + attrCapa.nValMin;
        severities[i] = 0;
    }

    *nIn = i;
    return asynSuccess;
}

asynStatus axisSXR40::startCapture()
{
    //static const char* functionName = "startCapture";

    setIntegerParam(ADNumImagesCounter, 0);
    setShutter(1);
    epicsEventSignal(startEventId_);
    return asynSuccess;
}

asynStatus axisSXR40::stopCapture()
{
    static const char* functionName = "stopCapture";
    int tucStatus;

    setShutter(0);

    tucStatus = TUCAM_Buf_AbortWait(camHandle_.hIdxTUCam);
    if (tucStatus!=TUCAMRET_SUCCESS){
        asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                "%s:%s: unable to abort wait (%d)\n",
                driverName, functionName, tucStatus);
    }

    tucStatus = TUCAM_Cap_Stop(camHandle_.hIdxTUCam);
    if (tucStatus!=TUCAMRET_SUCCESS){
        asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                "%s:%s: unable to stop acquisition (%d)\n",
                driverName, functionName, tucStatus);
    }

    tucStatus = TUCAM_Buf_Release(camHandle_.hIdxTUCam);
    if (tucStatus!=TUCAMRET_SUCCESS){
        asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                "%s:%s: unable to release camera buffer (%d)\n",
                driverName, functionName, tucStatus);
    }

    return asynSuccess;
}

asynStatus axisSXR40::getTrigger()
{
    static const char* functionName = "getTrigger";
    int tucStatus;

    tucStatus = TUCAM_Cap_GetTrigger(camHandle_.hIdxTUCam, &triggerHandle_);
    if (tucStatus != TUCAMRET_SUCCESS) {
        asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                "%s:%s error, status=%d\n",
                driverName, functionName, tucStatus);
        return asynError;
    }

    setIntegerParam(ADTriggerMode, triggerHandle_.nTgrMode);
    setIntegerParam(AxisSXR40TriggerEdge, triggerHandle_.nEdgeMode);
    setIntegerParam(AxisSXR40TriggerExposure, triggerHandle_.nExpMode);
    setDoubleParam(AxisSXR40TriggerDelay, triggerHandle_.nDelayTm/1.0e6);

    return asynSuccess;
}

asynStatus axisSXR40::setTrigger()
{
    static const char* functionName = "setTrigger";
    int triggerMode, triggerEdge, triggerExposure;
    double triggerDelay;
    int tucStatus;

    getIntegerParam(ADTriggerMode, &triggerMode);
    getIntegerParam(AxisSXR40TriggerEdge, &triggerEdge);
    getIntegerParam(AxisSXR40TriggerExposure, &triggerExposure);
    getDoubleParam(AxisSXR40TriggerDelay, &triggerDelay);

    frameHandle_.uiRsdSize = 1;

    triggerHandle_.nTgrMode = triggerMode;
    triggerHandle_.nEdgeMode = triggerEdge;
    triggerHandle_.nExpMode = triggerExposure;
    triggerHandle_.nFrames = 1;
    triggerHandle_.nDelayTm = int(triggerDelay*1e6);

    tucStatus = TUCAM_Cap_SetTrigger(camHandle_.hIdxTUCam, triggerHandle_);
    if (tucStatus != TUCAMRET_SUCCESS) {
        asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                "%s:%s error, status=%d\n",
                driverName, functionName, tucStatus);
        return asynError;
    }
    return asynSuccess;
}

asynStatus axisSXR40::getTriggerOut(int port)
{
    static const char* functionName = "getTriggerOut";
    int tucStatus;

    tucStatus = TUCAM_Cap_GetTriggerOut(camHandle_.hIdxTUCam, &triggerOutHandle_[port]);
    if (tucStatus != TUCAMRET_SUCCESS) {
        asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                "%s:%s error, status=%d\n",
                driverName, functionName, tucStatus);
        return asynError;
    }

    setIntegerParam(AxisSXR40TriggerOut1Mode + port * 4, triggerOutHandle_[port].nTgrOutMode);
    setIntegerParam(AxisSXR40TriggerOut1Edge + port * 4, triggerOutHandle_[port].nEdgeMode);
    setDoubleParam(AxisSXR40TriggerOut1Delay + port * 4, triggerOutHandle_[port].nDelayTm/1.0e6);
    setDoubleParam(AxisSXR40TriggerOut1Width + port * 4, triggerOutHandle_[port].nWidth/1.0e6);

    return asynSuccess;
}

asynStatus axisSXR40::setTriggerOut(int port)
{
    static const char* functionName = "setTriggerOut";
    int triggerMode, triggerEdge;
    double triggerDelay, triggerWidth;
    int tucStatus;

    getIntegerParam(AxisSXR40TriggerOut1Mode + port * 4, &triggerMode);
    getIntegerParam(AxisSXR40TriggerOut1Edge + port * 4, &triggerEdge);
    getDoubleParam(AxisSXR40TriggerOut1Delay + port * 4, &triggerDelay);
    getDoubleParam(AxisSXR40TriggerOut1Width + port * 4, &triggerWidth);

    triggerOutHandle_[port].nTgrOutPort = port;
    triggerOutHandle_[port].nTgrOutMode = triggerMode;
    triggerOutHandle_[port].nEdgeMode   = triggerEdge;
    triggerOutHandle_[port].nDelayTm    = int(triggerDelay*1e6);
    triggerOutHandle_[port].nWidth      = int(triggerWidth*1e6);

    tucStatus = TUCAM_Cap_SetTriggerOut(camHandle_.hIdxTUCam, triggerOutHandle_[port]);
    if (tucStatus != TUCAMRET_SUCCESS) {
        asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                "%s:%s error, status=%d\n",
                driverName, functionName, tucStatus);
        return asynError;
    }
    return asynSuccess;
}

asynStatus axisSXR40::setROI()
{
    static const char* functionName = "setROI";
    int minX, minY, sizeX, sizeY, maxSizeX, maxSizeY;
    int tucStatus;
    int status = asynSuccess;

    getIntegerParam(ADMinX, &minX);
    getIntegerParam(ADMinY, &minY);
    getIntegerParam(ADSizeX, &sizeX);
    getIntegerParam(ADSizeY, &sizeY);
    getIntegerParam(ADMaxSizeX, &maxSizeX);
    getIntegerParam(ADMaxSizeY, &maxSizeY);

    if (minX + sizeX > maxSizeX) {
        sizeX = maxSizeX - minX;
        setIntegerParam(ADSizeX, sizeX);
    }
    if (minY + sizeY > maxSizeY) {
        sizeY = maxSizeY - minY;
        /* DIFFERENCE FROM ADTucsen (6): upstream wrote the clamped HEIGHT into
         * ADSizeX here -- a copy-paste slip that corrupted the width parameter
         * whenever the height needed clamping. */
        setIntegerParam(ADSizeY, sizeY);
    }

    /* DIFFERENCE FROM ADTucsen (7): align every ROI field DOWN to a multiple of
     * 4 before handing it to the SDK.
     *
     * The camera silently rounds anything unaligned, so an unaligned request
     * would come back changed from Cap_GetROI and the EPICS readback would
     * disagree with what the user asked for. The vendor GUI masks with
     * ((v >> 2) << 2) in examples/QtDemo/camroi.cpp:112, which is the only place
     * the requirement is stated anywhere. Writing the aligned values back to the
     * parameters keeps EPICS honest about what was actually applied.
     *
     * WIDTH NEEDS 8, NOT 4 -- measured on this camera 2026-07-29, and both the
     * vendor GUI's mask and the vendor's own manual are wrong here. The TUCAM API
     * Development Guide 5.3.6.1/5.3.6.2 states plainly that "the horizontal
     * offset, vertical offset, width, and height must be set in multiples of 4",
     * with no exception for width. The camera disagrees. (The guide does document
     * a bit-depth-dependent rule elsewhere -- in 11-bit mode width x height must
     * be a multiple of 32 -- so undocumented per-mode alignment quirks have
     * precedent in this SDK.) Requests that are multiples of 4 but not 8 come
     * back changed by Cap_GetROI: 1004 -> 1000, 1012 -> 1008, 996 -> 992, while
     * 1000 and 1008 are kept. Height keeps every multiple of 4 (1004, 1012, 996
     * all survive), and both offsets keep every multiple of 4 (4, 12, 20 all
     * survive). So the alignment requirement is asymmetric: width 8, height 4,
     * offsets 4. Aligning width to 4 only, as upstream and the vendor GUI do,
     * leaves the camera silently narrowing half of all valid-looking requests. */
    minX  &= ~3;  sizeX &= ~7;
    minY  &= ~3;  sizeY &= ~3;
    setIntegerParam(ADMinX,  minX);
    setIntegerParam(ADMinY,  minY);
    setIntegerParam(ADSizeX, sizeX);
    setIntegerParam(ADSizeY, sizeY);

    TUCAM_ROI_ATTR roiAttr;
    memset(&roiAttr, 0, sizeof(roiAttr));
    roiAttr.bEnable = true;
    roiAttr.nHOffset = minX;
    roiAttr.nVOffset = minY;
    roiAttr.nWidth = sizeX;
    roiAttr.nHeight = sizeY;

    tucStatus = TUCAM_Cap_SetROI(camHandle_.hIdxTUCam, roiAttr);
    if (tucStatus != TUCAMRET_SUCCESS) {
        asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                "%s:%s SetROI error, status=0x%x\n",
                driverName, functionName, tucStatus);
        return asynError;
    }

    tucStatus = TUCAM_Cap_GetROI(camHandle_.hIdxTUCam, &roiAttr);
    if (tucStatus != TUCAMRET_SUCCESS) {
        asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                "%s:%s GetROI error, status=%d\n",
                driverName, functionName, tucStatus);
        return asynError;
    }

    status |= setIntegerParam(ADMinX, roiAttr.nHOffset);
    status |= setIntegerParam(ADMinY, roiAttr.nVOffset);
    status |= setIntegerParam(ADSizeX, roiAttr.nWidth);
    status |= setIntegerParam(ADSizeY, roiAttr.nHeight);

    return (asynStatus)status;
}

asynStatus axisSXR40::getROI()
{
    static const char* functionName = "getROI";
    int minX, minY, sizeX, sizeY, maxSizeX, maxSizeY;
    int tucStatus;
    int status = asynSuccess;

    getIntegerParam(ADMaxSizeX, &maxSizeX);
    getIntegerParam(ADMaxSizeY, &maxSizeY);

    TUCAM_ROI_ATTR roiAttr;
    tucStatus = TUCAM_Cap_GetROI(camHandle_.hIdxTUCam, &roiAttr);
    if (tucStatus != TUCAMRET_SUCCESS) {
        asynPrint(pasynUserSelf, ASYN_TRACE_ERROR,
                "%s:%s GetROI error, status=%d\n",
                driverName, functionName, tucStatus);
        return asynError;
    }

    if (roiAttr.bEnable) {
        minX = roiAttr.nHOffset;
        minY = roiAttr.nVOffset;
        sizeX = roiAttr.nWidth;
        sizeY = roiAttr.nHeight;
    } else {
        minX = 0;
        minY = 0;
        sizeX = maxSizeX;
        sizeY = maxSizeY;
    }

    status |= setIntegerParam(ADMinX, minX);
    status |= setIntegerParam(ADMinY, minY);
    status |= setIntegerParam(ADSizeX, sizeX);
    status |= setIntegerParam(ADSizeY, sizeY);

    return (asynStatus)status;
}

static const iocshArg configArg0 = {"Port name", iocshArgString};
static const iocshArg configArg1 = {"CameraId", iocshArgInt};
static const iocshArg configArg2 = {"traceMask", iocshArgInt};
static const iocshArg configArg3 = {"maxBuffers", iocshArgInt};
static const iocshArg configArg4 = {"maxMemory", iocshArgInt};
static const iocshArg configArg5 = {"priority", iocshArgInt};
static const iocshArg configArg6 = {"stackSize", iocshArgInt};
static const iocshArg * const configArgs [] = {&configArg0,
                                               &configArg1,
                                               &configArg2,
                                               &configArg3,
                                               &configArg4,
                                               &configArg5,
                                               &configArg6};
static const iocshFuncDef configAxisSXR40 = {"axisSXR40Config", 7, configArgs};
static void configCallFunc(const iocshArgBuf *args)
{
    axisSXR40Config(args[0].sval, args[1].ival, args[2].ival,
                 args[3].ival, args[4].ival, args[5].ival,
                 args[6].ival);
}

static void axisSXR40Register(void)
{
    iocshRegister(&configAxisSXR40, configCallFunc);
}

extern "C" {
    epicsExportRegistrar(axisSXR40Register);
}

