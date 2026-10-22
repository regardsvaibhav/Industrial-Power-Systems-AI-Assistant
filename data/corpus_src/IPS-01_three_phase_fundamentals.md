# IPS-01 Three-Phase Power Fundamentals

## 1. Scope

This note summarises the relationships used to calculate power in balanced three-phase alternating current (AC) systems found in industrial plants, commercial buildings and utility distribution networks. It covers line and phase quantities, wye and delta connections, real, reactive and apparent power, and the per-unit system. All formulas assume sinusoidal voltages and currents at fundamental frequency (50 Hz or 60 Hz) and a balanced load unless stated otherwise.

## 2. Line and phase quantities

A three-phase system has three voltages of equal magnitude displaced by 120 electrical degrees. The line-to-line voltage (V_LL) is measured between any two phase conductors. The line-to-neutral voltage (V_LN) is measured between a phase conductor and the neutral point.

In a balanced system V_LL = sqrt(3) x V_LN. For example, a 400 V line-to-line system has a line-to-neutral voltage of about 231 V, and a 480 V system has a line-to-neutral voltage of about 277 V.

In a wye (star) connection the line current equals the phase current, while the line voltage is sqrt(3) times the phase voltage. In a delta connection the line voltage equals the phase voltage, while the line current is sqrt(3) times the phase current.

## 3. Real, reactive and apparent power

Apparent power S, measured in volt-amperes (VA, kVA, MVA), is the product of voltage and current magnitudes. For a balanced three-phase load: S = sqrt(3) x V_LL x I_L.

Real (active) power P, measured in watts (W, kW, MW), is the power that performs useful work such as turning a shaft or producing heat: P = sqrt(3) x V_LL x I_L x cos(phi), where phi is the angle between the phase voltage and the phase current and cos(phi) is the displacement power factor.

Reactive power Q, measured in volt-amperes reactive (var, kvar, Mvar), is the power that oscillates between the source and the magnetic or electric fields of the load: Q = sqrt(3) x V_LL x I_L x sin(phi).

The three quantities form the power triangle: S squared = P squared + Q squared. Inductive loads such as induction motors and transformers absorb reactive power and have a lagging power factor. Capacitive loads supply reactive power and have a leading power factor.

## 4. Worked example

A balanced 400 V three-phase motor draws 100 A at a power factor of 0.85 lagging. The apparent power is sqrt(3) x 400 x 100 = 69.3 kVA. The real power is 69.3 x 0.85 = 58.9 kW. The reactive power is 69.3 x sin(acos(0.85)) = 69.3 x 0.527 = 36.5 kvar.

Note that the real power drawn from the supply is the electrical input. The mechanical output of the motor is lower by the motor losses, so shaft power equals input power multiplied by motor efficiency.

## 5. Single-phase versus three-phase

For a single-phase circuit the equivalent expressions are S = V x I and P = V x I x cos(phi), without the sqrt(3) factor. A frequent calculation error is applying the sqrt(3) factor to single-phase circuits, or omitting it for three-phase circuits when line-to-line voltage is used. When line-to-neutral voltage is used instead, three-phase power is P = 3 x V_LN x I_L x cos(phi), which gives the same result.

## 6. The per-unit system

Power system studies often express quantities in per unit (pu) of chosen base values. A base apparent power (S_base, for example 100 MVA) and a base voltage (V_base, usually the nominal line-to-line voltage of each zone) are selected; base current and base impedance are derived from them. Base impedance in ohms is Z_base = V_base squared / S_base.

Transformer and generator impedances are normally given in percent or per unit on their own nameplate rating. To convert an impedance from an old base to a new base: Z_new = Z_old x (S_new / S_old) x (V_old / V_new) squared.

The per-unit system makes transformer turns ratios disappear from the impedance diagram and keeps most quantities near 1.0 pu, which makes errors easier to spot.

## 7. Unbalance

Real installations are never perfectly balanced. Voltage unbalance is commonly expressed as the maximum deviation from the average line voltage divided by the average line voltage, in percent. Even small voltage unbalance causes much larger current unbalance in induction motors, which increases heating; motor manufacturers commonly recommend derating motors when voltage unbalance exceeds about 1 percent. The balanced formulas in this note should not be used for strongly unbalanced loads; instead each phase should be calculated separately and the results summed.
