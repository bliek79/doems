# DOEMS 3.0 - H5.1 Alpha84 safety choice recovery

Source of truth: bliek79/dummy-os-anker-ems 0.0.1-alpha.84
(commit 6ff976ab8e0b3a9641c32372dc8d2fdafc55db7d).
Published maintenance base: v0.3.0-alpha.8.8
(commit 041924b875e75a561defb0858df350b0ebe14b63).

## The demonstrated discrepancy
With identical forecasts and hour prices expanded to 288 quarters,
Alpha84 bought 3.2 kWh safety grid energy in hour 18; the former
native 15-minute preview bought 0.8 kWh in that same hour and shifted
the rest later. The 72-hour safety_valley comparison reported 15
safety-allocation differences.

## The precise correction
Original Alpha84 code decides the safety hour and stored-energy target
when quarter inputs contain no information beyond the hourly rate
for the causally relevant horizon. The selected hour is expanded into
four battery-energy quarters. True intra-hour source/tariff differences
continue through native quarter-price window selection. Future prices
beyond the last energy activity do not alter earlier safety choices.
The original hourly source implementation is unchanged.

## Verified acceptance evidence before release
At development commit 9e635c988121ccb8b8dcee5974181c79dfb49ba8,
the original-vs-source safety-allocation mismatch count in safety_valley
was 0 and the frozen 72-hour Preview choices matched.
947 functional regression tests passed on Python 3.12, 3.13 and 3.14,
with Foundation CI and general DOEMS CI green.
A separate release-branch CI must repeat all checks before publishing.

## Open after H5.1
Two source SOC comparison fields at hours 26 and 57 are still rounded
differently, and the physical Plan72 replay has separate discrepancies.
H5.2, H5.3, H5.4, H5.6, H6-H8 remain open as documented. No merge
into main, no Home Assistant modification, no physical execution.
