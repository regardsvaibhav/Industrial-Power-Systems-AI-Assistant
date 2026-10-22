# IPS-06 Voltage Drop and Short-Circuit Current Estimation

## 1. Voltage drop in feeders

Current flowing through cable resistance and reactance causes a voltage drop between source and load. For a balanced three-phase feeder the approximate line-to-line voltage drop is:

VD = sqrt(3) x I x L x (R x cos(phi) + X x sin(phi))

where I is the load current in amperes, L is the one-way route length in kilometres, R and X are the conductor resistance and reactance in ohms per kilometre, and cos(phi) is the load power factor. For a single-phase two-wire circuit the factor sqrt(3) is replaced by 2. Resistance should be taken at the expected conductor operating temperature, since copper resistance rises about 0.39 percent per degree C.

Example: a 400 V three-phase feeder 120 m long carries 150 A at power factor 0.85. The conductor has R = 0.153 ohm/km and X = 0.08 ohm/km. VD = 1.732 x 150 x 0.12 x (0.153 x 0.85 + 0.08 x 0.527) = 5.37 V, which is 1.34 percent of 400 V.

## 2. Voltage drop limits

Many wiring codes and design guides recommend that voltage drop be limited to about 3 percent on a feeder or branch circuit and about 5 percent in total from the service point to the furthest load. These figures are frequently recommendations rather than mandatory limits, and the applicable code for the installation must be checked. Motors are particularly sensitive: motor torque varies roughly with the square of applied voltage, so a 10 percent voltage dip reduces starting torque by about 19 percent.

## 3. Motor starting voltage dip

Direct-on-line motor starting draws inrush current of typically 5 to 7 times full-load current at a low power factor, often 0.2 to 0.4. The resulting voltage dip at the motor terminals and at the main bus should be checked, because excessive dip can stall the motor, cause contactors to drop out or disturb other equipment. Soft starters, star-delta starters and variable frequency drives reduce starting current.

## 4. Short-circuit current from a transformer

The maximum three-phase symmetrical fault current at the secondary terminals of a transformer, assuming an infinite (zero-impedance) upstream source, is:

I_sc = I_FL / (%Z / 100) = S_rated / (sqrt(3) x V_LL x %Z / 100)

Example: a 1000 kVA, 400 V transformer with 6 percent impedance has I_FL = 1443 A and I_sc = 1443 / 0.06 = 24.1 kA. Because the infinite-source assumption ignores utility and cable impedance, it overestimates the fault current and is conservative for checking equipment interrupting ratings. It is not conservative for checking that protective devices will trip quickly enough on minimum faults, or for arc flash studies, where lower fault currents can produce longer clearing times and higher incident energy.

## 5. Including the source impedance

When the utility fault level at the transformer primary is known as S_sc_source (MVA), the source impedance in per unit on the transformer base is Z_source = S_rated / S_sc_source. The total impedance is the sum of source and transformer per-unit impedances (treating them as in phase as a simplification), and I_sc = I_FL / Z_total_pu. For example, with a 250 MVA source and the 1000 kVA, 6 percent transformer above, Z_source = 1 / 250 = 0.004 pu, Z_total = 0.064 pu and I_sc = 1443 / 0.064 = 22.5 kA.

## 6. X/R ratio and equipment ratings

The ratio of reactance to resistance (X/R) of the fault path determines the DC offset of the fault current and therefore the peak asymmetrical current. High X/R ratios, typical close to large transformers and generators, increase the peak current. Switchgear and circuit breakers must have short-circuit making and breaking ratings, and busbars a short-time withstand rating, at least equal to the prospective fault current at their location. Motor contribution, typically estimated as about 4 to 6 times the full-load current of running motors for the first few cycles, should be added when large motor loads are present.
