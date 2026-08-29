import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["**/.next/**", "**/node_modules/**", "**/dist/**", "**/*.config.js"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    // Build scripts run in Node, not the browser.
    files: ["**/scripts/**/*.mjs", "**/*.config.mjs"],
    languageOptions: {
      globals: { console: "readonly", process: "readonly", URL: "readonly" },
    },
  },
  {
    rules: {
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      "@typescript-eslint/consistent-type-imports": "error",
      "no-console": ["error", { allow: ["warn", "error"] }],
    },
  },
);
