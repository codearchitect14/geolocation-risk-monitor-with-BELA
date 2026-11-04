import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({ baseDirectory: import.meta.dirname });

const config = [
  { ignores: [".next/**", "node_modules/**", "reports/**", "scripts/**", "next-env.d.ts", "public/**"] },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
];

export default config;
