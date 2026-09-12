# workflow/ — full tier; needs the camera and real storage

How the beamline will actually drive the detector, and what its files must contain.

- `test_scan_like.py`: the ophyd sequence (stage → N triggers → unstage) in both file
  layouts: one HDF5 file per scan (`NumCapture 0`, capture until unstaged) and one file per
  point (`NumCapture` = frames per point, auto-close, `FileNumber` increments). Unique ids
  contiguous within a file and increasing across files.
- `test_hdf5_contract.py`: the dataset paths and the exact NDAttributes set a written file
  carries (`helpers/expected.EXPECTED_DATASETS`, `EXPECTED_NDATTRIBUTES`), via `h5check -l`.
  Analysis code breaks silently when these move; a change here is a deliberate edit.

Files are written to `--outdir` and deleted after checking.
