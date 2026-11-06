import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // `next/link` prefetches every link in the viewport, and each prefetch is a
  // full server render. This site is dense with links between products,
  // suppliers and categories, so that default multiplies one page view into
  // dozens of renders. `@/components/link` wraps it with prefetching off;
  // importing `next/link` directly would silently reintroduce the default.
  {
    rules: {
      "no-restricted-imports": [
        "error",
        {
          paths: [
            {
              name: "next/link",
              message:
                "Import { Link } from '@/components/link' instead — it defaults prefetch off.",
            },
          ],
        },
      ],
    },
  },
  {
    // The one place allowed to import it: the wrapper itself.
    files: ["components/link.tsx"],
    rules: { "no-restricted-imports": "off" },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
