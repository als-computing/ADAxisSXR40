# image/ — needs the camera; marked `hardware_state`

Dark-frame sanity through Stats1. Expected to xfail while the camera emits its synthetic
256-level ramp (info/known-gaps/TODO.md §8). The reporter test never fails and prints
`RAMP PRESENT` or `real sensor data`; when the xfails turn into XPASS the camera is fixed.
