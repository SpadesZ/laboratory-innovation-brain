# Research problem: turning waveguide simulation intent into working FDTD simulations

## Problem

Photonic waveguide experiments are designed and checked with finite-difference time-domain (FDTD) simulation in Ansys Lumerical FDTD.
A researcher states what they want to simulate as a high-level design intent in natural language.
Turning that intent into an executable simulation program and a physically meaningful simulation setup is the step to be solved.

## Motivation

Translating design intent into a Lumerical simulation is difficult for general-purpose language models.
The Lumerical scripting and Python interface is proprietary, so little of it is publicly available for models to learn from.
Whether a simulation setup is good depends on photonic judgment about geometry, materials, sources, monitors, mesh and the interpretation of outputs.

## Constraints

The simulator is licensed commercial software, and every simulation run costs compute time.
A program that runs is not sufficient: the simulation setup must also be physically meaningful.
The work concerns photonic waveguide experiments.

## What a solution must achieve

From a natural-language request, it produces a Lumerical FDTD simulation that actually executes.
The simulation setup is physically meaningful for the requested waveguide experiment: geometry, materials, sources, monitors and mesh are appropriate.
The simulation outputs are interpreted correctly.

## Question

How can natural-language design intent for photonic waveguide experiments be turned, reliably and with little manual effort, into executable and physically meaningful Lumerical FDTD simulations?
