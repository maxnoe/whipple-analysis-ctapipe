INPUTS := $(wildcard data/*.fz.xz)
PEDESTAL_IMAGES := $(patsubst data/%.fz.xz,build/%.ped.dl1.h5,$(INPUTS))
PEDESTAL_STATS := $(patsubst data/%.fz.xz,build/%.ped.mon.h5,$(INPUTS))
POINTING := $(patsubst data/%.fz.xz,build/%.pointing.mon.h5,$(INPUTS))
DL1 := $(patsubst data/%.fz.xz,build/%.dl1.h5,$(INPUTS))
PYTHON ?= python

.PHONY: all
all: $(PEDESTAL_STATS) $(DL1) build/raw10_run_summary.csv

.PHONY: dl1
dl1: $(DL1)

.PHONY: pointing
pointing: $(POINTING)

.DELETE_ON_ERROR:
.SECONDARY: $(PEDESTAL_IMAGES) $(POINTING)

build:
	mkdir -p $@

clean:
	rm -rf build

build/%.pointing.mon.h5: data/%.fz.xz scripts/extract_pointing.py | build
	$(PYTHON) scripts/extract_pointing.py "$<" "$@" --overwrite

build/%.dl1.h5: data/%.fz.xz build/%.pointing.mon.h5 build/%.ped.mon.h5 configs/process_dl0_to_dl1.yaml | build
	ctapipe-process \
		--config configs/process_dl0_to_dl1.yaml \
		--input "$<" \
		--output "$@" \
		--HDF5MonitoringSource.input_files="['$(word 2,$^)', '$(word 3,$^)']" \
		--provenance-log="$@.provlog" \
		--log-file="$@.log" \
		--overwrite \
		--log-level=INFO \
		--progress

build/%.ped.dl1.h5: data/%.fz.xz configs/process_pedestal.yaml | build
	ctapipe-process \
		--config configs/process_pedestal.yaml \
		--input "$<" \
		--output "$@" \
		--provenance-log="$@.provlog" \
		--log-file="$@.log" \
		--overwrite \
		--log-level=INFO \
		--progress

build/%.ped.mon.h5: build/%.ped.dl1.h5 configs/calculate_pixel_stats.yaml scripts/pedestal_statistics_to_coefficients.py | build
	ctapipe-calculate-pixel-statistics \
		--config configs/calculate_pixel_stats.yaml \
		--input_url "$<" \
		--output_path "$@" \
		--provenance-log="$@.provlog" \
		--log-file="$@.log" \
		--overwrite  \
		--log-level=INFO
	$(PYTHON) scripts/pedestal_statistics_to_coefficients.py "$@"


build/raw10_run_summary.csv:
	curl -sSfL https://zenodo.org/records/16890876/files/raw10_run_summary.csv.xz?download=1 | xz -d -c > $@


.PHONY: clean
