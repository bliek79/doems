from pathlib import Path
R=Path(__file__).resolve().parents[1]/"custom_components"/"doems"
def test_three_live_sources_and_roundtrip():
    config=(R/"config_flow.py").read_text()
    runtime=(R/"energy_need_runtime.py").read_text()
    assert 'sensor.anker_solix_solarbank_max_ac_185_soc' in config
    assert 'sensor.anker_solix_solarbank_max_ac_185_accucapaciteit' in config
    assert 'number.anker_solix_solarbank_max_ac_185_ontladingslimiet' in config
    assert 'CONF_ENERGY_NEED_ROUNDTRIP_EFFICIENCY, 84.64' in config
    assert 'CONF_ENERGY_NEED_RESERVE_PERCENT, 5.0' in config
    assert "sqrt(float(roundtrip) / 100)" in runtime
    assert "capacity_state.state if capacity_state is not None else None" in runtime
    assert "minimum_state.state if minimum_state is not None else None" in runtime
    assert "for key in (CONF_ENERGY_NEED_SOC_ENTITY, CONF_ENERGY_NEED_CAPACITY_ENTITY, CONF_ENERGY_NEED_MIN_SOC_ENTITY)" in runtime
