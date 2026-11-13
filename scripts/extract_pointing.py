#!/usr/bin/env python3
"""Extract Whipple tracking records into a ctapipe HDF5 monitoring file.

Use --append to attach pointing to an existing DL1 file.
Linear extrapolation covers event times outside the recorded tracking range.
Requires the same Python environment as ctapipe-process and ctapipe_io_whipple.
"""

import argparse
from pathlib import Path
from uuid import uuid4

import astropy.units as u
import ctao_datamodel.models.dataproducts as dp
import fzreader
import numpy as np
import tables
from astropy.table import Table
from astropy.time import Time
from ctapipe.instrument import SubarrayDescription
from ctapipe.io import EventSource
from ctapipe.io.astropy_helpers import write_table
from ctapipe.io.datawriter import DATA_MODEL_VERSION
from ctapipe.io.hdf5dataformat import DL0_TEL_POINTING_GROUP, OBSERVATION_BLOCK_TABLE
from ctapipe.io.metadata import Contact, write_product_metadata_hdf5
from ctapipe_io_whipple.eventsource import _event_time


def extrapolate_to_events(pointing, first_event, last_event):
    """Extend to the event bounds in TAI MJD using the closest two samples."""
    times = pointing["time"].tai.mjd
    targets = [
        time for time in (first_event, last_event)
        if time < times[0] or time > times[-1]
    ]
    if not targets:
        return pointing
    if len(pointing) < 2:
        raise ValueError("At least two tracking samples are needed to extrapolate")

    azimuth = np.unwrap(pointing["azimuth"].quantity.to_value(u.rad))
    altitude = pointing["altitude"].quantity.to_value(u.rad)
    result = pointing.copy()
    for time in sorted(set(targets)):
        i, j = (0, 1) if time < times[0] else (-2, -1)
        fraction = (time - times[i]) / (times[j] - times[i])
        az = azimuth[i] + fraction * (azimuth[j] - azimuth[i])
        alt = altitude[i] + fraction * (altitude[j] - altitude[i])
        if not -np.pi / 2 <= alt <= np.pi / 2:
            raise ValueError("Extrapolated pointing altitude is outside [-90, 90] degrees")
        result.add_row([
            Time(time, format="mjd", scale="tai"),
            ((az % (2 * np.pi)) * u.rad).to_value(result["azimuth"].unit),
            (alt * u.rad).to_value(result["altitude"].unit),
        ])
    result.sort("time")
    return result


def read_pointing(input_path):
    """Read actual telescope alt/az and UTC MJD timestamps from tracking banks."""
    rows = []
    first_event = np.inf
    last_event = -np.inf
    with fzreader.FZReader(str(input_path)) as reader:
        for record in reader:
            if not record.get("record_was_decoded", False):
                continue
            if record.get("record_type") in ("event", "frame"):
                # Match WhippleEventSource's GPS timestamps and DAQ fallback.
                event_time, time_source = _event_time(record)
                mjd = event_time.tai.mjd
                if time_source == "unknown" or not np.isfinite(mjd):
                    raise ValueError("Cannot cover an event with an unknown timestamp")
                first_event = min(first_event, mjd)
                last_event = max(last_event, mjd)
                continue
            if record.get("record_type") != "tracking":
                continue

            row = (
                record["record_time_mjd"],
                record["telescope_az_deg"],
                record["telescope_el_deg"],
            )
            # fzreader uses zero for unavailable/invalid record timestamps.
            if not np.all(np.isfinite(row)) or row[0] <= 0 or not -90 <= row[2] <= 90:
                raise ValueError(f"Invalid tracking timestamp or pointing: {row}")
            rows.append(row)

    if not rows:
        raise ValueError(f"No decoded tracking records in {input_path}")

    values = np.asarray(rows, dtype=np.float64)
    values = values[np.argsort(values[:, 0], kind="stable")]
    if np.any(np.diff(values[:, 0]) == 0):
        raise ValueError("Tracking records contain duplicate timestamps")

    pointing = Table(
        {
            "time": Time(values[:, 0], format="mjd", scale="utc"),
            "azimuth": (values[:, 1] * u.deg).to(u.rad),
            "altitude": (values[:, 2] * u.deg).to(u.rad),
        }
    )
    if np.isfinite(first_event):
        pointing = extrapolate_to_events(pointing, first_event, last_event)
    return pointing


def extract_pointing(input_path, output_path, overwrite=False, append=False):
    """Write a monitoring file or attach pointing to an existing event file."""
    input_path = Path(input_path)
    output_path = Path(output_path)
    if input_path.resolve() == output_path.resolve():
        raise ValueError("Input and output paths must differ")
    if append and not output_path.is_file():
        raise FileNotFoundError(f"Cannot append to missing file: {output_path}")
    if output_path.exists() and not (overwrite or append):
        raise FileExistsError(f"{output_path} exists; use --overwrite to replace it")

    pointing = read_pointing(input_path)
    with EventSource(input_url=input_path) as source:
        subarray = source.subarray
        (tel_id,) = subarray.tel_ids
        (obs_id,) = source.observation_blocks

    if append:
        existing_subarray = SubarrayDescription.from_hdf(output_path)
        if not SubarrayDescription.check_matching_subarrays([subarray, existing_subarray]):
            raise ValueError("Input and output have incompatible subarray descriptions")
        # Preserve the event file's instrument description, metadata, and event data.
        with tables.open_file(output_path, mode="a") as h5file:
            obs_ids = h5file.get_node(OBSERVATION_BLOCK_TABLE).col("obs_id")
            if set(obs_ids) != {obs_id}:
                raise ValueError("Input and output have different observation IDs")
            write_table(
                pointing,
                h5file,
                f"{DL0_TEL_POINTING_GROUP}/tel_{tel_id:03d}",
                overwrite=overwrite,
            )
        return len(pointing)

    product = dp.Product(
        description="Whipple telescope pointing extracted from FZ tracking records",
        creation_time=Time.now(),
        data=dp.ProductType(
            level=dp.DataLevel.DL0,
            division=dp.DataDivision.MONITORING,
            association=dp.DataAssociation.TELESCOPE,
            type=dp.DataType.POINTING,
        ),
        instance=dp.InstanceIdentifier(id=uuid4(), obs_id=int(obs_id)),
        curation=dp.Curation(),
        model=dp.DataModel(name="ctapipe", version=DATA_MODEL_VERSION),
        contact=Contact().to_model(),
    )

    with tables.open_file(output_path, mode="w") as h5file:
        subarray.to_hdf(h5file)
        write_table(pointing, h5file, f"{DL0_TEL_POINTING_GROUP}/tel_{tel_id:03d}")
        write_product_metadata_hdf5(product, h5file)

    return len(pointing)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Input .fz file (also supports compression)")
    parser.add_argument("output", type=Path, help="Output HDF5 file")
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Replace an existing output (with --append, replace only the pointing table)",
    )
    parser.add_argument(
        "--append", action="store_true",
        help="Attach pointing to an existing DL1 file, preserving events and metadata",
    )
    args = parser.parse_args()
    count = extract_pointing(
        args.input, args.output, overwrite=args.overwrite, append=args.append
    )
    print(f"Wrote {count} pointing samples to {args.output}")


if __name__ == "__main__":
    main()
