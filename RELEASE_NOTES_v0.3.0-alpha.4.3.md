# DOEMS 3.0 - Alpha 4.3 - Energy Need startup migration hotfix

Fixes the Home Assistant startup `KeyError: 'energy_need_capacity_entity'` after upgrading from Alpha 4.1 to Alpha 4.2 while previously saved options still contain the numeric battery capacity. Missing source selectors no longer abort the full DOEMS integration; Energy Need remains invalid until the user selects the three confirmed Anker battery entities in DOEMS configuration.

No battery control commands are added. Alpha 4.1 and 4.2 releases remain unchanged.

After HACS update and Home Assistant restart, open DOEMS Configure, select SOC, battery capacity and discharge limit, retain 5% extra reserve and 84.64% roundtrip, submit options and verify the 11 Energy Need entities.
