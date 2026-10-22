# IPS-02 Power Factor and Reactive Power Compensation

## 1. What power factor means

Power factor (PF) is the ratio of real power to apparent power: PF = P / S. It ranges from 0 to 1. A power factor of 1.0 (unity) means that all current delivered does useful work. A lower power factor means that more current, and therefore larger cables, transformers and switchgear, is needed to deliver the same real power.

True power factor includes the effect of harmonic currents, while displacement power factor considers only the phase angle between fundamental-frequency voltage and current. With non-linear loads such as variable frequency drives and rectifiers, true power factor can be noticeably lower than displacement power factor.

## 2. Causes of low power factor

The most common cause of low power factor in industrial plants is lightly loaded induction motors. An induction motor needs magnetising current regardless of load, so a motor running at 25 percent of rated load may have a power factor of 0.5 or less, while the same motor at full load may reach 0.85 to 0.9. Other causes include transformers operating at light load, welding equipment, induction furnaces and fluorescent lighting with magnetic ballasts.

## 3. Why utilities penalise low power factor

Low power factor increases current in the utility network, which increases resistive losses (proportional to current squared), voltage drop and the capacity that must be reserved in generators and lines. Many utilities therefore apply a penalty or a kVA-based demand charge when the customer's average power factor falls below a threshold, often in the range 0.90 to 0.95. The exact threshold and tariff are utility specific and must be checked against the applicable tariff.

## 4. Sizing capacitors for correction

The reactive power that a capacitor bank must supply to raise the power factor of a load from PF1 to PF2 at constant real power P is:

Qc = P x (tan(acos(PF1)) - tan(acos(PF2)))

Example: a plant load of 500 kW at power factor 0.75 lagging is to be corrected to 0.95 lagging. tan(acos(0.75)) = 0.882 and tan(acos(0.95)) = 0.329, so Qc = 500 x (0.882 - 0.329) = 277 kvar. The apparent power falls from 667 kVA to 526 kVA, which releases about 140 kVA of transformer and cable capacity.

## 5. Where to install capacitors

Capacitors can be installed at individual motors, at group or feeder level, or centrally at the main switchboard. Individual correction gives the largest loss reduction in the plant wiring but costs more and must be coordinated with motor protection; the capacitor rating at a motor should not exceed the motor's no-load magnetising reactive power, otherwise self-excitation can produce dangerous overvoltage when the motor is disconnected while still spinning. Central automatic capacitor banks with several switched steps are the most common solution because they follow the load as it varies.

## 6. Risks of overcorrection and harmonics

Correcting beyond unity produces a leading power factor, which can raise voltage at light load and may also be penalised. Capacitors combined with the inductance of the supply transformer form a parallel resonant circuit. If the resonant frequency is close to a harmonic produced by drives or rectifiers (typically the 5th or 7th harmonic), harmonic voltage and current can be strongly amplified, causing capacitor failures and fuse operation. In installations with significant non-linear load, detuned capacitor banks with series reactors (for example 7 percent reactors, which tune the bank to about 3.8 times the fundamental frequency: about 189 Hz on a 50 Hz system or 227 Hz on a 60 Hz system, safely below the 5th harmonic) or active harmonic filters should be considered. A harmonic study is recommended before installing large capacitor banks.

## 7. Approximate parallel resonance check

The harmonic order of parallel resonance between a capacitor bank and the supply can be estimated as h = sqrt(S_sc / Q_c), where S_sc is the short-circuit power at the capacitor bus in MVA and Q_c is the capacitor rating in Mvar. For example, a 0.5 Mvar bank on a bus with 12.5 MVA short-circuit level resonates near h = sqrt(25) = 5, the 5th harmonic, which is a poor design if six-pulse drives are present.
