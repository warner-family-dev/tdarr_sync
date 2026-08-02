import js from "@eslint/js";
import nextPlugin from "@next/eslint-plugin-next";
import reactHooks from "eslint-plugin-react-hooks";
import { defineConfig, globalIgnores } from "eslint/config";
import tseslint from "typescript-eslint";

export default defineConfig([
  js.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    extends: tseslint.configs.recommended,
  },
  {
    files: ["**/*.{js,mjs,cjs,ts,tsx}"],
    plugins: {
      "@next/next": nextPlugin,
      "react-hooks": reactHooks,
    },
    rules: {
      ...nextPlugin.configs.recommended.rules,
      ...nextPlugin.configs["core-web-vitals"].rules,
      ...reactHooks.configs.flat["recommended-latest"].rules,
      "react-hooks/set-state-in-effect": "off",
    },
  },
  {
    files: ["scripts/**/*.js"],
    languageOptions: {
      sourceType: "commonjs",
      globals: {
        __dirname: "readonly",
        process: "readonly",
        require: "readonly",
      },
    },
  },
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts"]),
]);
