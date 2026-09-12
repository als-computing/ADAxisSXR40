# pvs/ — needs the IOC

Every record the serving driver's template declares (plus ADBase/NDArrayBase) connects,
has the declared record type, CA type, enum strings, PREC and EGU. Identity strings.
Every safe setpoint round-trips through its `_RBV`, including the image-processing knobs
within the SDK's measured ranges. Everything is restored.
