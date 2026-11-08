# MATLAB / Simulink + NI Linux simulation reference

Offline capture inspection, a toy thermal/fault simulator, and a C fixed-step runtime connected only to a synthetic UDP plant.

![Status: provided as is](https://img.shields.io/badge/status-provided--as--is-lightgrey) ![License: Apache--2.0](https://img.shields.io/badge/license-Apache--2.0-blue)

Created at [Exowatt](https://exowatt.com). This project is governed independently under a neutral physical-AI organization and remains vendor-neutral.

> [!WARNING]
> **SIMULATION ONLY — NOT APPROVED FOR REAL HARDWARE.** This is a feasibility/reference implementation, **not a production controller**, a safety system, or an NI-DAQmx/MATLAB/Simulink replacement. The published runtime has **only a synthetic UDP HAL**; no real NI output backend, NI installer, stand deployment kit, real equipment inventory, or validated physical interlock is included. Never connect this reference to actuators or use its example thresholds, channels, toy proportional law, or modeled inhibit as hardware safety settings.

## Status

Provided as-is. The Python tools and C model tests run offline; the optional Docker bench uses a synthetic plant. MATLAB helper code has **not** been executed under a licensed MATLAB installation. No support, hardware compatibility, real-time guarantees, or physical safety qualification is implied.

## Install

Clone the repository and use Python 3.10+ (standard library only). For C model unit tests, install a C11 compiler and `make`; building the Linux UDP runtime additionally needs Linux with `clock_nanosleep`. None of these offline checks needs NI software, MATLAB, a network service, or a hardware device.

## Quickstart (offline, no hardware)

From the repository root:

```sh
python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m ni_offline tests/fixtures/pi-synthetic-capture.json
PYTHONPATH=src python3 -m ni_offline simulate --scenario crash-restart --summary
python3 tools/ci_smoke.py
make -C runtime test
```

The inspector accepts a local synthetic/replay JSON trace and reports `hardware_access: false` and `actuation: false`; it rejects measured-hardware claims. `ci_smoke.py` writes an ignored `build/synthetic-ci-report.json`. `make -C runtime test` compiles and runs the C model unit tests, without running the controller. On Linux, `make -C runtime all test` also builds `ctrl_udp`; it has no NI backend.

For an **optional** container-only fault exercise, install Docker Compose and run `python3 tools/fault_campaign.py`. It builds two isolated simulation containers, publishes the dashboard to **loopback** at `http://127.0.0.1:18080`, records a synthetic report in `build/`, and tears them down. This is not part of the minimal quickstart.

## Configuration

The offline inspector's `--max-gap-ms` default is 250 ms, solely a synthetic rejection threshold. The simulator offers `--scenario` values `baseline`, `crash-restart`, `sensor-fault`, `network-loss`, `airflow-loss`, and `manual-rearm`; all parameters are illustrative. The Linux `ctrl_udp` target talks only to the synthetic plant over UDP and uses `--hal-arg plant:47000` within Docker Compose. Do not point it at a physical-device gateway.

The optional `matlab/+nistand/` source illustrates model configuration, code generation and packaging; it does not deploy or operate hardware. Its output is a generated artifact for **separate review**, not a qualified stand image. See [synthetic example](docs/synthetic-example.md) and [MATLAB notes](matlab/README.md).

## Prerequisites and exclusions

For **optional, unvalidated** model generation, obtain and license MATLAB, Simulink, Simulink Coder and Embedded Coder independently from MathWorks; none is bundled. NI Linux DAQmx is a **user-supplied proprietary prerequisite for any separately authorized future NI experiment**, not required for these offline tests and **never bundled, fetched or installed by this export**. Check NI's supported hardware/OS matrix and all license terms independently before any such work. No NI driver, LabVIEW VI, generated MATLAB artifact, firmware, proprietary SDK or real capture is included.

## Safety and limits

The software-modeled guardian is not a physical inhibit; simulated heater/blower values are numbers in memory or UDP packets inside a container network, not actuator output. A passing CI run proves only these software boundaries and toy scenarios. Real hardware work requires a different, separately reviewed design, ownership/permission and physical independent safety assessment. The synthetic [I/O example](docs/synthetic-example.md) is not a wiring or device specification.

## License

Original code is licensed under [Apache-2.0](LICENSE). See [NOTICE](NOTICE) for attribution. Proprietary MathWorks and NI components are not distributed here.

## Contributing

See [CONTRIBUTING](https://github.com/couplet-physical-ai/.github/blob/main/CONTRIBUTING.md). Contributions require DCO sign-off (`git commit -s`); no CLA is required. Do not submit captures, hardware mappings, proprietary SDKs or vendor-generated artifacts.

## Security

Please report vulnerabilities privately using [GitHub private vulnerability reporting](https://github.com/couplet-physical-ai/matlab-simulink-ni-linux-driver/security/advisories/new). See the [security policy](https://github.com/couplet-physical-ai/.github/blob/main/SECURITY.md); do not open a public issue.
