TOP=../..
include $(TOP)/configure/CONFIG
#----------------------------------------
#  ADD MACRO DEFINITIONS AFTER THIS LINE

LIBRARY_IOC += axisSXR40
LIB_SRCS    += axisSXR40.cpp

# TUDefine.h picks its target OS from predefined macros and selects the macOS
# branch on x86_64 Linux, which changes BOOL from 4 bytes to 1 and would
# corrupt every struct carrying one. Without this the build fails outright at
# TUDefine.h:1276 ("'WORD' does not name a type"). Not optional.
USR_CXXFLAGS_Linux += -DTUCAM_TARGETOS_IS_LINUX
USR_INCLUDES       += -I$(TUCAM_INCLUDE)

ifeq ($(TUCAM_EXTERNAL),YES)
LIB_SYS_LIBS += TUCam
else
LIB_LIBS += TUCam
endif

DBD += axisSXR40Support.dbd

include $(ADCORE)/ADApp/commonLibraryMakefile

#=============================

include $(TOP)/configure/RULES
#----------------------------------------
#  ADD RULES AFTER THIS LINE
