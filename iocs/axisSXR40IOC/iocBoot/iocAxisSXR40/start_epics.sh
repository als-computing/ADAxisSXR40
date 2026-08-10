export EPICS_CA_SERVER_PORT=5077
medm -x -macro "P=AXIS:SXR40:,R=cam1:" ../../../../axisSXR40App/op/adl/AxisSXR40.adl &
../../bin/linux-x86_64/axisSXR40App st.cmd
