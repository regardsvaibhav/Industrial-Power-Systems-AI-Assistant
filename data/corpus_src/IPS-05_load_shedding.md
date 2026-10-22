# IPS-05 Load Shedding Principles (Educational)

## 1. Purpose and safety notice

Load shedding is the deliberate disconnection of selected loads to restore the balance between generation and demand and prevent frequency or voltage collapse. This note describes general principles for education and planning studies only. Actual load shedding schemes must be designed by qualified engineers in accordance with the requirements of the responsible grid operator and site safety procedures. Nothing in this note is an operating instruction.

## 2. Types of load shedding

Under-frequency load shedding (UFLS) disconnects load automatically in stages when frequency falls below set thresholds. Under-voltage load shedding (UVLS) disconnects load when voltage remains low, typically to prevent voltage collapse in heavily loaded transmission areas. Contingency-based or fast load shedding uses breaker status signals: when a generator or tie-line breaker opens, a controller immediately sheds a pre-calculated amount of load, without waiting for frequency to fall. Manual load shedding is ordered by operators, for example during rotating outages when there is a sustained capacity shortage.

## 3. Staged UFLS schemes

UFLS is normally arranged in several stages, each shedding a block of load at a progressively lower frequency threshold with a short time delay to avoid tripping on transient dips. A purely illustrative scheme for a 50 Hz system might shed 10 percent of load at 49.0 Hz, another 10 percent at 48.8 Hz and another 10 percent at 48.6 Hz. Actual thresholds, stage sizes and delays are specified by each grid operator and differ between regions and between 50 Hz and 60 Hz systems.

## 4. Load priority classification

A load shedding plan ranks loads by the consequence of interrupting them. A common approach uses priority tiers:

- Priority 1, critical: life safety and emergency systems, fire pumps, emergency lighting, control and protection supplies, and processes where interruption creates a hazard. These are never shed.
- Priority 2, essential: loads whose loss causes significant production loss or equipment damage, for example continuous process drives and cooling for critical equipment. Shed only as a last resort.
- Priority 3, important: loads that can tolerate short interruptions, for example batch processes, compressors with storage, and office HVAC.
- Priority 4, non-essential: loads that can be interrupted with little consequence, for example comfort heating, non-critical lighting, water heaters and EV charging.

Shedding proceeds from the lowest priority (highest tier number) upward until the deficit is covered, and within a tier larger loads are often shed first to minimise the number of switching operations.

## 5. Determining the amount to shed

The required shed amount is the power deficit plus a margin to restore a positive spinning reserve: Shed required = demand - available generation + required reserve. Shedding too little leaves the system vulnerable to further decline; shedding too much can cause over-frequency and unnecessary customer impact. Because some loads such as motors fall with frequency (load damping), detailed studies use dynamic simulation, but simple steady-state balance calculations are useful for first-pass planning.

## 6. Restoration

Shed loads should be restored gradually, in reverse priority order, only after frequency has recovered and sufficient reserve is available. Restoring large blocks at once can cause a second frequency dip. Motor restarts produce inrush currents of typically 5 to 7 times rated current, which should be considered when restoring large motor loads.

## 7. Hypothetical example

An islanded plant has two gas engines of 2.0 MW each and a demand of 3.6 MW. One engine trips, leaving 2.0 MW of generation. With a required reserve of 0.2 MW, the shed required is 3.6 - 2.0 + 0.2 = 1.8 MW. Shedding first the Priority 4 loads (0.6 MW) and then the Priority 3 loads (1.4 MW) gives 2.0 MW shed, which covers the requirement while protecting Priority 1 and Priority 2 loads.
