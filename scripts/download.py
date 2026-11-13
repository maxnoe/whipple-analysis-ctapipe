from pathlib import Path
from fzreader import FZDataArchive
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("download")


runs = {
    "flatfield": [5105],
    "on": [5106, 5108, 5109, 5110, 5111], 
    "off": [5107, ],
}

archive = FZDataArchive("zenodo", verbose=True)

base = Path("data")
for kind, run_ids in runs.items():
    outdir = base / kind
    outdir.mkdir(parents=True, exist_ok=True)

    for run_id in run_ids:
        log.info("Downloading run %d", run_id)
        fdata = archive.get_run_by_number(str(run_id))

        path = (outdir / fdata.filename())
        path.write_bytes(fdata.compressed_data())
        log.info("Successfully downloaded run %d to path %s", run_id, path)
