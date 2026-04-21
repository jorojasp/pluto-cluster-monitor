# Python Migration

## Purpose of the Migration

The migration from MATLAB to Python is intended to preserve the validated functionality of the original prototype while improving the software architecture for long-term development.

The goal is not simply to reproduce the previous code line by line. Instead, the aim is to build a cleaner backend that maintains the original measurement logic while improving modularity, maintainability, and deployment flexibility.

## Why Python

Python is a suitable next step for several reasons:

- it supports a more modular backend design,
- it integrates naturally with open SDR tooling,
- it allows clearer separation between backend and visualization,
- it is better suited for future embedded Linux deployment,
- and it provides a stronger base for distributed system designs.

## Migration Philosophy

The Python migration follows a staged approach.

Rather than porting the entire MATLAB system at once, development proceeds in layers:

1. rebuild hardware discovery and stable radio mapping,
2. rebuild receiver and transmitter control,
3. reproduce continuous acquisition,
4. reproduce power and SNR estimation for SineWave mode,
5. restore strongest/weakest and group comparison logic,
6. restore plotting,
7. and only afterward move on to more complex digital receiver chains.

This approach reduces the risk of mixing too many moving parts at once.

## What Has Been Carried Over

The following ideas from the MATLAB version are intentionally preserved:

- one transmitter and multiple receivers,
- logical grouping of receivers,
- continuous monitoring,
- real-time metric computation,
- strongest and weakest receiver selection,
- group-level comparison,
- support for multiple signal modes,
- and future scalability.

## What Is Being Improved

The Python backend introduces changes that are not meant to alter the scientific purpose of the project, but to improve the software design.

These changes include:

- separating hardware access from high-level application flow,
- resolving radios by stable serial identifiers instead of fragile port assumptions,
- avoiding repeated discovery logic during runtime,
- introducing explicit acquisition modules,
- storing metric history for later plotting,
- and preparing the codebase for future backend/frontend separation.

## Current Scope

At the current stage, the Python migration focuses primarily on the backend and on the SineWave mode.

This means the short-term priorities are:

- stable radio discovery,
- correct mapping from configured radios to connected radios,
- transmitter and receiver initialization,
- continuous sample acquisition,
- received power calculation,
- SNR estimation,
- strongest and weakest receiver determination,
- group comparison,
- and exportable plots.

More advanced digital processing modes will be migrated after this basic path is stable.

## Difference Between the MATLAB and Python Stages

The MATLAB implementation already proved the concept with a complete interactive environment.

The Python version is still under active development and should currently be understood as a backend reconstruction stage. Its purpose is to establish a robust software foundation before rebuilding higher-level visualization and extending the modulation support.

## Migration as a Praxis project Topic

The migration itself is valuable from a praxis project perspective because it includes:

- architectural redesign,
- integration of SDR hardware with a new software stack,
- preservation of experimental logic across platforms,
- improvement of system robustness,
- and preparation for future scalability.

This makes the migration a meaningful engineering contribution rather than a simple rewrite.

## Immediate Next Steps

The next technical steps in the migration are:

- finalize SineWave backend behavior,
- align metric computation with the MATLAB baseline where appropriate,
- restore real-time style plots through backend history,
- port BPSK processing,
- then port QPSK,
- then port 16QAM,
- and later revisit distributed TX/RX architectures.
