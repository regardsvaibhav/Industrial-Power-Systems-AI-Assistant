# IPS-04 Generation-Demand Balance and Frequency Control

## 1. Why frequency reflects balance

In an AC power system the electrical frequency is set by the rotational speed of synchronous generators. When generation exceeds demand, the surplus energy accelerates the rotating machines and the frequency rises. When demand exceeds generation, energy is drawn from the rotating masses, the machines slow down and the frequency falls. System frequency is therefore a continuous indicator of the balance between generation and demand, including losses.

## 2. Inertia and rate of change of frequency

Immediately after a sudden loss of generation, the rate of change of frequency (ROCOF) is limited by the stored kinetic energy of the synchronised rotating machines. The inertia constant H, in seconds, is the stored kinetic energy at rated speed divided by the machine MVA rating; typical values are 2 to 9 seconds for synchronous generators. For the whole system the initial ROCOF can be estimated as ROCOF = (delta P x f0) / (2 x H_sys x S_sys), where delta P is the power imbalance, f0 the nominal frequency, H_sys the aggregate inertia constant and S_sys the total rated MVA of synchronised machines.

Example: a 50 Hz system with 2000 MVA of online generation and H_sys = 4 s loses a 100 MW unit. The initial ROCOF is 100 x 50 / (2 x 4 x 2000) = 0.31 Hz/s. Systems with a high share of inverter-based generation such as solar and wind have lower synchronous inertia and therefore experience faster frequency changes unless synthetic inertia or fast frequency response is provided.

## 3. Primary control: governor droop

Generator speed governors respond automatically to frequency deviations. Droop is the percentage change in frequency that causes the governor to move the unit from zero to full output. A typical droop setting is 4 to 5 percent. With 5 percent droop, a frequency drop of 5 percent (2.5 Hz on a 50 Hz system) would drive the unit from zero to rated output. The power change of a unit is delta P = -(delta f / f0) / R x P_rated, where R is the droop in per unit.

Example: a 100 MW unit with 5 percent droop experiences a frequency drop of 0.2 Hz on a 50 Hz system (0.4 percent). Its output increases by (0.004 / 0.05) x 100 = 8 MW, provided headroom is available.

Primary control stabilises the frequency at a new value but does not return it to nominal; a steady-state frequency error remains.

## 4. Secondary and tertiary control

Secondary control, often implemented as automatic generation control (AGC) or load-frequency control, adjusts generator setpoints over tens of seconds to minutes to restore frequency to nominal and to restore scheduled interchange with neighbouring areas. Tertiary control re-dispatches generation over longer time frames to restore the reserves used by primary and secondary control.

## 5. Reserves and the N-1 criterion

Operators hold operating reserves so that the system can withstand the loss of any single element, which is known as the N-1 criterion. Spinning reserve is unloaded capacity on generators already synchronised to the grid. Non-spinning reserve can be started and loaded within a defined time. A common planning rule is that spinning reserve should be at least equal to the output of the largest single generating unit online, so that its loss can be covered. Reserve margin in this assistant's calculations is defined as (available generation - demand) / demand x 100 percent.

## 6. Islanded systems and microgrids

Industrial plants with on-site generation may operate as an island when disconnected from the utility. In an island the plant generators alone must match load and losses, inertia is small, and large motor starts or the trip of a single generator can cause large frequency excursions. Islanded plants therefore rely on fast load shedding schemes (see IPS-05) and on keeping enough spinning reserve on the running generators. If demand exceeds available generation in an island, either load must be shed or the system will collapse.
