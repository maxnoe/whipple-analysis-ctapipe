#!/usr/bin/env python3
"""Add pedestal subtraction coefficients to a Whipple pixel-statistics file.

The pedestal images must come from un-subtracted, single-sample Whipple
waveforms with the same ADC-to-photoelectron scaling as the science events.
For these waveforms the integrated image mean is also the per-sample offset.
"""

import argparse
from pathlib import Path

import numpy as np
import tables
from astropy.table import Table
from astropy.time import Time
from ctapipe.io.astropy_helpers import read_table, write_table
from ctapipe.io.hdf5dataformat import (
    DL1_CAMERA_COEFFICIENTS_GROUP,
    DL1_PIXEL_STATISTICS_GROUP,
)


def make_coefficients(statistics):
    """Use each statistics chunk from its start time until the next chunk."""
    statistics = statistics.copy()
    statistics.sort("time_start")
    time = statistics["time_start"]
    if not isinstance(time, Time) or len(time) == 0:
        raise ValueError("Expected non-empty statistics with Time timestamps")
    if not np.all(np.isfinite(time.tai.mjd)) or np.any(np.diff(time.tai.mjd) <= 0):
        raise ValueError("Statistics must have distinct, finite start times")

    mean = np.asarray(statistics["mean"], dtype=np.float64).copy()
    if mean.ndim != 3 or mean.shape[1] != 1:
        raise ValueError("Expected Whipple means with shape (n_chunks, 1, n_pixels)")
    outlier_mask = np.asarray(statistics["outlier_mask"], dtype=bool).copy()
    if outlier_mask.shape != mean.shape:
        raise ValueError("Outlier mask and mean shapes differ")
    is_valid = np.asarray(statistics["is_valid"], dtype=bool)
    is_valid = is_valid.reshape(len(time), -1).all(axis=1)
    outlier_mask |= ~np.isfinite(mean) | ~is_valid[:, None, None]
    # Invalid pixels are handled by CameraCalibrator using outlier_mask.
    mean[outlier_mask] = 0

    return Table({
        "time": time,
        "pedestal_offset": mean,
        # Whipple has one channel and no gain selection. Its single-sample
        # DL1 image is 1D; ctapipe currently multiplies this in place by factor
        # without squeezing a singleton channel axis. Store pixel-wise ones.
        "factor": np.ones_like(mean[:, 0, :]),
        "time_shift": np.zeros_like(mean),
        "outlier_mask": outlier_mask,
        "is_valid": is_valid,
    })


def add_coefficients(path, overwrite=False):
    """Add coefficients in place, preserving statistics and file metadata."""
    statistics_group = f"{DL1_PIXEL_STATISTICS_GROUP}/sky_pedestal_image"
    with tables.open_file(path, mode="r+") as h5file:
        # Read and validate all input tables before changing the file.
        coefficients = {
            node.name: make_coefficients(read_table(h5file, node._v_pathname))
            for node in h5file.iter_nodes(statistics_group, classname="Table")
            if node.name.startswith("tel_")
        }
        if not coefficients:
            raise ValueError(f"No sky pedestal statistics in {path}")
        if not overwrite:
            for name in coefficients:
                if f"{DL1_CAMERA_COEFFICIENTS_GROUP}/{name}" in h5file:
                    raise FileExistsError("Coefficients already exist; use --overwrite")
        for name, table in coefficients.items():
            write_table(
                table, h5file, f"{DL1_CAMERA_COEFFICIENTS_GROUP}/{name}",
                overwrite=overwrite,
            )
    return sum(len(table) for table in coefficients.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Existing Whipple pedestal statistics HDF5 file")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing coefficients")
    args = parser.parse_args()
    if not args.input.is_file():
        parser.error(f"File does not exist: {args.input}")
    count = add_coefficients(args.input, overwrite=args.overwrite)
    print(f"Added {count} pedestal coefficient rows to {args.input}")


if __name__ == "__main__":
    main()
