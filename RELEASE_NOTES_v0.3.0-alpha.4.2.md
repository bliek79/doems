# DOEMS 3.0 - Chapter 4 Energy Need - Alpha 4.2

Correction of v0.3.0-alpha.4.1 for read-only Home Assistant live validation.

- SOC: `sensor.anker_solix_solarbank_max_ac_185_soc`
- Battery capacity: `sensor.anker_solix_solarbank_max_ac_185_accucapaciteit` (kWh)
- Hardware discharge limit: `number.anker_solix_solarbank_max_ac_185_ontladingslimiet` (%)
- Configurable additional safety reserve: 5% initial user choice.
- Configurable roundtrip efficiency: 84.64% initial user choice, symmetric model sqrt(0.8464) = 0.92 for charging and discharging.
- Recompute on changes to all three source entities and the forecasts.
- Invalid or missing source data invalidates Energy Need; no fixed capacity fallback.
- No physical battery control commands.

## HA validation required
Configure Energy Need in DOEMS options. Verify all eleven entities, changing SOC/capacity/hardware limit, and missing forecast behavior. Release is for observation only.
