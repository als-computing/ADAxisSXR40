TOP=../..
include $(TOP)/configure/CONFIG
#----------------------------------------
#  ADD MACRO DEFINITIONS AFTER THIS LINE

PROD_NAME = axisSXR40App
PROD_IOC_Linux += $(PROD_NAME)
PROD_IOC_WIN32 += $(PROD_NAME)

# <name>.dbd will be created from <name>Include.dbd
DBD += $(PROD_NAME).dbd
$(PROD_NAME)_DBD += axisSXR40Support.dbd

# <name>_registerRecordDeviceDriver.cpp will be created from <name>.dbd
$(PROD_NAME)_SRCS += $(PROD_NAME)_registerRecordDeviceDriver.cpp $(PROD_NAME)Main.cpp

# Add locally compiled object code
PROD_LIBS           += axisSXR40
ifeq ($(TUCAM_EXTERNAL),YES)
PROD_SYS_LIBS       += TUCam
else
    ifeq ($(STATIC_BUILD),YES)
    PROD_SYS_LIBS       += TUCam
    else
    PROD_LIBS           += TUCam
    endif
endif

ifeq (windows-x64-debug, $(findstring windows-x64-debug, $(T_A)))
USR_LDFLAGS_WIN32 += /NODEFAULTLIB:LIBCMT.lib
endif

# --------------------------------------------------------------------------
# libTUCam symbol-interposition workaround.
#
# libTUCam.so.1 statically bundles libjpeg, libtiff, libpng and zlib and exports
# every one of their symbols -- 160 jpeg_*, 171 tiff, 399 png_, 37
# deflate/inflate. That makes it interpose on ADCore's real copies:
# libaxisSXR40.so is this IOC's first DT_NEEDED, so libTUCam is reached at
# dependency level 2 before libNDPlugin's libjpeg/libtiff/libpng, and the
# dynamic linker's breadth-first search binds to TUCam's bundled versions.
#
# Without this, NDFileJPEGConfigure() in commonPlugins.cmd segfaults inside
# libTUCam's jpeg_CreateCompress before iocInit is ever reached. Both copies
# report version "9b 17-Jan-2016" but they are different builds -- the
# jpeg_CreateCompress bodies are 0x18a and 0x13b bytes -- so the version /
# sizeof(struct jpeg_compress_struct) check on entry fails and libjpeg takes its
# ERREXIT path. ERREXIT dereferences cinfo->err, and ADCore's NDFileJPEG.cpp:310
# calls jpeg_create_compress() one line *before* it assigns jpegInfo.err, so that
# pointer is still uninitialised: the process dies instead of reporting the
# mismatch. Binding the matching libjpeg makes the check pass, which keeps that
# upstream ordering latent rather than fatal.
#
# libtiff and libpng are included for the same reason. They do not crash at
# configure time because neither plugin touches its library until a file is
# written -- so those would fail later and only when saving, which is worse.
#
# Linking the real libraries into the executable makes them level-1
# dependencies, which outrank libTUCam at level 2. --no-as-needed is required
# because the IOC's own objects reference none of these symbols, so the linker
# would otherwise discard them; --as-needed is restored straight afterwards so
# the rest of the link is unchanged -- in particular -lTUCam stays dropped from
# the executable and keeps arriving via libaxisSXR40.so, which is what keeps it
# at level 2.
#
# zlib is deliberately left out: its ABI carries no version handshake, so an
# interposed deflate/inflate is far less likely to misbehave, and forcing a
# second zlib into the link risks conflicting with the one HDF5 already uses.
ifeq ($(JPEG_EXTERNAL),NO)
USR_LDFLAGS_Linux += -Wl,--no-as-needed
USR_LDFLAGS_Linux += -L$(ADSUPPORT)/lib/$(T_A) -ljpeg -ltiff -lpng
USR_LDFLAGS_Linux += -Wl,--as-needed
endif

include $(ADCORE)/ADApp/commonDriverMakefile

#=============================

include $(TOP)/configure/RULES
#----------------------------------------
#  ADD RULES AFTER THIS LINE

