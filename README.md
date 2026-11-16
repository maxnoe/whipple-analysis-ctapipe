# ctapipe analysis of Whipple 10m open dataset

The project contains a [pixi](https://pixi.prefix.dev/latest/) env
for the required software and a `Makefile` to run it.

To produce the merged on and off hdf5 files at DL1, run:

```
$ pixi run make download
$ pixi run make
```

Then you can look at the output data using the jupyter notebook:

```
$ pixi run jupyter lab alpha.ipynb
```
