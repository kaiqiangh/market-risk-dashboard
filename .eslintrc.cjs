module.exports = {
  root: true,
  env: { browser: true, es2020: true, node: true },
  extends: [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended",
    "plugin:react-hooks/recommended",
    "prettier",
  ],
  // src/schemas/generated is emitted by scripts/gen_ts_contracts.py (#101). Linting it is a
  // dead end in both directions: a violation cannot be fixed in place (the file is
  // regenerated on the next model change), and the blanket disable the emitter writes is
  // itself reported as unused under --report-unused-disable-directives.
  ignorePatterns: ["dist", "coverage", "node_modules", "public/data", "src/schemas/generated"],
  parser: "@typescript-eslint/parser",
  plugins: ["react-refresh"],
  overrides: [
    {
      // Test files may use explicit any (negative test cases need to construct invalid payloads)
      files: ["tests/**/*.{ts,tsx}"],
      rules: {
        "@typescript-eslint/no-explicit-any": "off",
      },
    },
  ],
  rules: {
    "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
    "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
  },
};
