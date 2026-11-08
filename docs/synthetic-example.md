# Synthetic example target (not a device specification)

This export intentionally has **no real target inventory**. For demonstrations only, the target is a software process with a toy thermal value, a hypothetical heater request and blower request, and an independent **software** inhibit. No chassis/module/channel numbers, wiring, power stage or real-device behavior are defined or implied. `src/ni_offline/simulation.py` generates deterministic sample traces, `runtime/model/controller/` is a hand-written controller stand-in, and `docker/plant/` hosts an isolated synthetic UDP plant and dashboard.

The fixture `tests/fixtures/pi-synthetic-capture.json` has three samples: synthetic temperature values 20, 21, 22 °C and heater-reference percentages 0, 10, 20, at artificial 100 ms intervals. Its provenance fields explicitly say synthetic; they do not identify a person, installation or hardware device. These numbers have no safety significance.

The offline JSON inspector and unit tests use only Python's standard library. The C model test uses a C11 compiler and `make`. On Linux, `make -C runtime all` can build the UDP-to-simulator runtime; there is no NI library link target. The optional Docker Compose scenario uses loopback for its web dashboard and an isolated container network for UDP. No real hardware connection or authorization is offered by this example.
