# DOEMS 0.1.0-alpha.7.5 - Full Brand Logo Icon Fix

Alpha7.5 is intentionally small. DOEMS has one approved brand logo. The general Home Assistant integration icon now shows that complete existing logo instead of a separately cropped sub-mark.

## Fixed

- `brand/logo.png` remains the single approved source artwork.
- The technical square Home Assistant icon roles are rebuilt from the **complete** logo without cropping:
  - `icon.png` 256x256
  - `icon@2x.png` 512x512
  - `dark_icon.png` 256x256
  - `dark_icon@2x.png` 512x512
- Aspect ratio is preserved and unused square space stays transparent.
- Dark mode changes only the existing logo's dark text treatment; it is not a second logo.
- CI rebuilds the brand assets and fails when committed files differ from the deterministic output.

## Unchanged

- No MDI replacement and no new artwork.
- No entity-specific icon changes.
- Energy Forecast unchanged.
- Solar P3.1 unchanged.
- Prices P4 and the Alpha7.4 gas-versus-electricity sensor unchanged.
- Native 15 minutes / 72 hours / 288 slots unchanged.
- Prices 76 hours / 304 internal slots unchanged.
- `physical_execution_authority=false`.

## Live check

After HACS upgrade and Home Assistant restart, check only the general DOEMS integration/device branding. It should show the complete existing DOEMS brand logo. Functional sensor values should remain unchanged.
