# compat/ — full tier; needs the IOC and a recorded baseline

`capture_baseline.py` dumps every PV (type, count, enum strings, PREC, EGU, and values for
small scalars) of whichever IOC is serving into `baselines/<driver>-<date>.json`. Run it
while `ioc-xv4040` is active to record ADTucsen (`tests/run.sh capture`; the swap itself
is manual). `test_compat_baseline.py` then diffs our live IOC against the newest ADTucsen
baseline; `compat_rules.py` is the contract of intended differences, and anything else is
a failure. The full report lands in `tests/.results/compat-report.txt`.

`XV4040:Pva1:Image` shows as unconnected in every baseline: it is the pvAccess-only
NTNDArray served by NDPluginPva, listed by `pvlist` but not a Channel Access record. It is
compared by `acquire/test_plugins.py` over pvAccess instead.

First baseline: `adtucsen-2026-09-11.json` (7529 PVs, 12 write-error records, autosave
2391). First comparison the same day: 7 intended differences, 0 unintended.
