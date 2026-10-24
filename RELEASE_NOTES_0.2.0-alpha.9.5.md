# DOEMS 0.2.0-alpha.9.5

Recovery of the reset R9 architecture from PR #105 with the P0 Combined branch.
Manual and Automatic feed Combined; only the Combined bridge owns the shared
execution controller. Physical authority remains disabled by default and is
not enabled by installation. Dynamic power caps remain deferred.

Preserves native 15 minute / 72 hour / 288 slot planning, manual priority,
Prices DST estimates and EnergyZero startup retry. Restores main's Solar
quarter-roll publication without provider I/O and retains the R8 controller
regression tests. Historical Alpha76 EMS entry points are superseded by the
reset architecture and remain available in existing branches and tags.

Release gates check version identity, the complete regression suite, HACS ZIP
contents and SHA256. Published tags are never moved or overwritten.
Home Assistant installation and live battery behavior are not verified by
these software tests. No Home Assistant configuration is changed.
