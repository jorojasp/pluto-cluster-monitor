# Problem Statement

## Motivation

Traditional wireless measurement setups are often expensive, difficult to scale, and limited to a small number of channels. This creates a gap between theoretical learning and hands-on experimentation, especially in university environments and research settings where flexible and low-cost testbeds are needed.

This project addresses that gap by developing a scalable multi-SDR platform based on ADALM-Pluto radios for real-time analysis of digital communication signals. The platform is intended to support continuous monitoring of received power and Signal-to-Noise Ratio (SNR), comparison of multiple receiver nodes, and flexible experimentation with different transmission modes and modulation schemes.

## Core Problem

The main problem addressed by this project is how to build an affordable, modular, and scalable system capable of monitoring and comparing multiple radio receivers in real time, while remaining flexible enough for teaching, research, and future extensions.

In the original MATLAB-based implementation, the system already demonstrated real-time monitoring of power and SNR, support for multiple modulation modes, and automatic comparison of receivers organized into clusters. However, the architecture was still strongly tied to a host-computer-centered MATLAB workflow.

The current stage of the project focuses on porting the backend to Python in order to preserve the validated logic of the MATLAB prototype while improving modularity, maintainability, and long-term deployability.

## Project Objective

The objective of the project is to develop a flexible multi-radio analysis platform that:

- uses one transmitter and multiple receivers based on ADALM-Pluto SDR hardware,
- continuously acquires and analyzes received signals,
- computes metrics such as received power and SNR,
- identifies the strongest and weakest receivers,
- compares logical receiver groups,
- supports different transmission modes and digital modulations,
- and provides a solid backend foundation for future visualization, distributed acquisition, and embedded deployment.

## Why the Python Migration Matters

The Python migration is not simply a translation of the code into another language. It is a restructuring effort intended to transform the original prototype into a cleaner and more extensible platform.

The migration aims to:

- separate hardware access from analysis and visualization,
- reduce dependency on a single monolithic application,
- improve maintainability and code organization,
- prepare the system for future deployment on embedded Linux platforms,
- and enable later expansion toward distributed transmitter/receiver architectures.

## Expected Impact

The project is relevant in several areas:

- **Education:** students can observe real radio behavior and better understand modulation, power, and SNR.
- **Research:** the platform can be used for channel studies, comparative receiver analysis, and experimentation with modulation schemes.
- **Applied engineering:** the system can serve as a low-cost monitoring and diagnostic platform, with future potential for localization or protocol-level experimentation.
