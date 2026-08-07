// Pins the process timezone before the module under test is evaluated, so the
// local-day grouping test is deterministic on every runner (#94).
process.env.TZ = "America/New_York";
