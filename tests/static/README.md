# static/ — no IOC, no camera

Parses the source tree only: template drvInfo strings against the driver's `createParam`
calls (the `T_*`→`AXIS_*` rename bug), request files, `st.cmd` and the systemd files,
documentation links, the template diff against ADTucsen, and the helpers themselves.
This is the folder CI can run. `tests/run.sh static`.
