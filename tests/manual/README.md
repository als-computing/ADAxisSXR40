# manual/ — procedures that cannot be automated here

Nothing in this folder runs under pytest. These need hardware or an IOC restart:

1. **External trigger in.** Pulse generator on the trigger input; `TriggerMode`
   Standard, then Synchronous, then Global; one frame per pulse; `TriggerEdge` both
   polarities; `TriggerDelay` visible as a shift against the pulse on a scope.
   Record: frames per N pulses, jitter, and the `TriggerExposure` Gate behaviour.
2. **Trigger out.** Scope on each of the 3 outputs; `TriggerOutNMode` Exposure Start /
   Readout End / High / Low; `TriggerOutNEdge` — remember the output encoding is
   inverted relative to the input (0 = RisingEdge on outputs). Record widths and delays.
3. **TEC enable.** Only with the coolant loop verified flowing and someone at the
   detector. Write `TECEnable` 0 then 1, watch `TemperatureActual` for 10 minutes each.
   The capability is documented as decoupled from the cooler (known-gaps TODO §2).
4. **Autosave round-trip.** Change exposure, ROI and a plugin setting; wait 60 s;
   `sudo systemctl restart ioc-axissxr40`; confirm the values came back and that
   `boot/` still passes.
5. **Camera power-cycle for the ramp.** After it, `tests/run.sh smoke` must show the two
   `image/` xfails as XPASS and `RAMP PRESENT` gone; then remove the xfail markers.

Record results as a dated file in `info/` (camera/ or known-gaps/), not here.
