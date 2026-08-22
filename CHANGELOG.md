# Changelog

## Unreleased

- Risk model: RSI now uses standard 14-period Wilder smoothing. Existing RSI-derived
  values may shift slightly; the change is covered by the golden score test and is not a
  threshold or weight recalibration.
