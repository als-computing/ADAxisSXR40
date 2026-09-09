# h5check — is this HDF5 file what the IOC says it is?

`NumCaptured` and `DroppedArrays` only say the plugin *thinks* it wrote every frame.
`h5check` opens the file with an HDF5 library that is **not** the IOC's own (ADSupport
ships one) and prints, per file:

- rank, dimensions (`frames × height × width`), element type and chunk shape;
- min / max / mean / zero-fraction of the **first, middle and last frame**;
- whether `NDArrayUniqueId` runs 1 … N with no gap or repeat;
- the frame rate from the camera timestamps stored in the file (`NDArrayTimeStamp`) and
  from the EPICS timestamps — an independent check on any wall-clock measurement.

## Build

```bash
S=/usr/local/epics/support/areaDetector/ADSupport      # your ADSupport
gcc -O2 -o h5check h5check.c -I$S/include/os/Linux \
    -L$S/lib/linux-x86_64 -lhdf5 -lzlib -lsz -Wl,-rpath,$S/lib/linux-x86_64
```

## Use

```bash
./h5check /home/$USER/axis-perf-tmp/perf4096_000.h5
for f in /home/$USER/axis-perf-tmp/perf*.h5; do ./h5check $f; done
```

## Reading the output

Good — what a dark sensor on this camera should look like (illustrative values; the
expected order of magnitude comes from the characterisation notes: mean ≈ 68 ADU at 50 ms,
max in the hundreds to low thousands from hot pixels, and the numbers changing from frame
to frame):

```
dims=[90 x 4096 x 4096] type=uint16 chunk=[1 x 4096 x 4096]
  first  frame     0: min=<tens> max=<hundreds–thousands> mean=~68 zeros=0.00%
  UniqueId: n=90 first=1 last=90 span=90 missing=0 nonmonotonic=0
  TimeStamp (camera): span=10.297 s -> 8.6 fps
```

Bad — what was found on 2026-08-26 (the camera's own test ramp, not an image):

```
  first  frame     0: min=0 max=65280 mean=32640.0 zeros=0.39%   <- identical on every frame
```

Mean exactly 32640.0 with max 65280 and 1/256 zeros is a 256-level ramp in the high
byte. See [info/known-gaps/TODO.md](../../info/known-gaps/TODO.md) §8.

Dataset paths are the ADCore default layout (`/entry/data/data`,
`/entry/instrument/NDAttributes/*`); a custom XML layout will need the paths changed
at the top of `h5check.c`.
