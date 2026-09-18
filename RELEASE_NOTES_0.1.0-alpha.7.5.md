# DOEMS 0.1.0-alpha.7.5 - Single Brand Logo Fix

Alpha7.5 is intentionally small: DOEMS has one approved brand logo and the general Home Assistant integration icon must show that complete logo instead of a cropped sub-mark.

## Fixed

- `brand/logo.png` remains the single approved source artwork.
- The Home Assistant icon roles now reuse the complete logo artwork:
  - `icon.png` = `logo.png`
  - `icon@2x.png` = `logo@2x.png`
  - `dark_icon.png` = `dark_logo.png`
  - `dark_icon@2x.png` = `dark_logo@2x.png`
- The brand builder no longer crops a separate icon out of the logo.
- CI verifies byte-for-byte that icon roles and their corresponding logo variants match.

## Unchanged

- No MDI replacement and no second logo.
- No entity-specific icon changes.
- Energy Forecast unchanged.
- Solar P3.1 unchanged.
- Prices P4 and the Alpha7.4 gas-versus-electricity sensor unchanged.
- Native 15 minutes / 72 hours / 288 slots unchanged.
- Prices 76 hours / 304 internal slots unchanged.
- `physical_execution_authority=false`.

## Live check

After HACS upgrade and Home Assistant restart, check only the general DOEMS integration/device branding. It should show the existing complete DOEMS brand logo. Functional sensor values should remain unchanged.
