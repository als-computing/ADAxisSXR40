# performance/ — full tier; needs the camera

`roi-rate-test.sh` is the measurement script (moved here from `info/performance/`, where
the method and the dated results stay). `test_rate_regression.py` runs it acquire-only at
4096, 512 and 32 rows and asserts each rate is within 5 % of the recorded reference for
this host (`helpers/expected.RATE_REFERENCE_FPS`).
