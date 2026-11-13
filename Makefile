ON_INPUTS := $(wildcard data/on/*.fz.xz)
OFF_INPUTS := $(wildcard data/off/*.fz.xz)
FF_INPUTS := $(wildcard data/ff/*.fz.xz)

INPUTS := $(ON_INPUTS) $(OFF_INPUTS)

PEDESTAL_IMAGES := $(patsubst data/%.fz.xz,build/%.ped.dl1.h5,$(INPUTS))
PEDESTAL_STATS := $(patsubst data/%.fz.xz,build/%.ped.mon.h5,$(INPUTS))

POINTING := $(patsubst data/%.fz.xz,build/%.pointing.mon.h5,$(INPUTS))

DL1_ON := $(patsubst data/%.fz.xz,build/%.dl1.h5,$(ON_INPUTS))
DL1_OFF := $(patsubst data/%.fz.xz,build/%.dl1.h5,$(OFF_INPUTS))

PYTHON ?= python

.PHONY: all
all: build/on.dl1.h5 build/off.dl1.h5

.PHONY: dl1
dl1: $(DL1)

.PHONY: pointing
pointing: $(POINTING)

.DELETE_ON_ERROR:
.SECONDARY: $(PEDESTAL_IMAGES) $(POINTING)

build:
	mkdir -p $@ $@/on $@/off $@/ff

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


build/on.dl1.h5: $(DL1_ON)
	ctapipe-merge -o $@ $(DL1_ON)


build/off.dl1.h5: $(DL1_OFF)
	ctapipe-merge -o $@ $(DL1_OFF)


build/raw10_run_summary.csv:
	curl -sSfL https://zenodo.org/records/16890876/files/raw10_run_summary.csv.xz?download=1 | xz -d -c > $@


download: | data
	python scripts/download_data.py

data:
	mkdir -p data


.PHONY: clean download

# keep intermediate files
.PRECIOUS: build/%.ped.mon.h5 
