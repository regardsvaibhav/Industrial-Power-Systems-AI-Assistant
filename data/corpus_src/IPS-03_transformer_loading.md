# IPS-03 Transformer Loading, Losses and Thermal Limits

## 1. Rating and loading percentage

A power transformer is rated in apparent power (kVA or MVA), not in kW, because its heating depends on current and voltage regardless of power factor. Transformer loading in percent is the actual apparent power divided by the rated apparent power: Loading (%) = S_actual / S_rated x 100.

Example: a 1000 kVA transformer supplying 720 kW at power factor 0.8 carries 720 / 0.8 = 900 kVA and is therefore loaded to 90 percent, even though the real power is only 72 percent of the kVA rating. This is why improving power factor can release transformer capacity.

Rated full-load current on a three-phase winding is I_FL = S_rated / (sqrt(3) x V_LL). For a 1000 kVA transformer with a 400 V secondary, I_FL = 1000 / (1.732 x 0.4) = about 1443 A.

## 2. Cooling classes

Oil-immersed transformers are identified by a four-letter cooling code. ONAN means oil natural, air natural: the oil circulates by convection and the radiators are cooled by natural air flow. ONAF adds fans for forced air cooling and typically allows a higher rating, for example a transformer rated 20 MVA ONAN might be rated 25 MVA ONAF. OFAF and ODAF use pumps to force oil flow. Dry-type transformers use codes such as AN (air natural) and AF (air forced). The kVA rating that applies is the one for the cooling stage actually in service; if the fans fail, the transformer must be returned to its ONAN rating.

## 3. Losses and efficiency

Transformer losses have two main components. No-load (core or iron) losses are caused by magnetising the core and are almost constant whenever the transformer is energised, regardless of load. Load (copper or winding) losses are caused by current flowing through winding resistance and vary with the square of the load: P_load_loss = P_load_loss_rated x (S / S_rated) squared.

Efficiency = output power / (output power + no-load loss + load loss). Maximum efficiency occurs at the load at which load losses equal no-load losses, i.e. at a per-unit load of sqrt(P_no_load / P_load_loss_rated). For a transformer with 1.5 kW no-load loss and 10.5 kW full-load load loss, maximum efficiency occurs near 38 percent load.

Worked example: the same 1000 kVA transformer at 75 percent load and power factor 0.9 delivers 675 kW. Load loss is 10.5 x 0.75 squared = 5.91 kW, total loss is 7.41 kW and efficiency is 675 / 682.4 = 98.9 percent.

## 4. Thermal limits and insulation ageing

The life of a transformer is determined mainly by the ageing of its cellulose (paper) insulation, which depends on the winding hot-spot temperature, moisture and oxygen. For thermally upgraded paper, a common reference is a continuous hot-spot temperature of 110 degrees C, which corresponds to normal life expectancy. The ageing rate roughly doubles for every 6 to 7 degrees C of hot-spot temperature above that reference and halves for every similar decrease below it. Short periods of overload can therefore be acceptable if they are offset by periods of lighter loading, but sustained overload consumes insulation life quickly.

Planned overloads above nameplate rating should be assessed with a recognised loading guide for oil-immersed transformers together with the manufacturer's data. As a general rule of thumb for this assistant, a transformer is classified as: normal at or below 80 percent loading, high between 80 and 100 percent, and overloaded above 100 percent. These bands are planning guidance, not protection settings.

## 5. Impedance and voltage regulation

Transformer percent impedance (%Z) is the percentage of rated voltage that must be applied to one winding, with the other winding short-circuited, to circulate rated current. Typical values are 4 to 6 percent for distribution transformers of 500 to 2500 kVA and 8 to 12 percent or more for large power transformers. Higher impedance limits short-circuit current but increases voltage drop under load.

## 6. Parallel operation

Transformers operated in parallel should have the same voltage ratio, the same vector group (phase displacement), the same polarity and phase sequence, and similar percent impedance (commonly within about 10 percent of each other). Unequal impedances cause the transformers to share load in inverse proportion to their impedances, so the lower-impedance unit may become overloaded before the combined rating is reached. Unequal ratios cause a circulating current even at no load.
