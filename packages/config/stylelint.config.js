/**
 * Stylelint config for مِسك (Misk).
 *
 * The rule that matters: physical CSS properties are BANNED.
 *
 * The product is Arabic-first and RTL by default. `margin-left: 4px` is not a
 * style choice here, it is a bug that only shows up in the language the product
 * is actually written in. Logical properties (`margin-inline-start`) are correct
 * in both directions, so the ban is absolute rather than advisory.
 */

/** Physical property -> the logical property to use instead. */
const PHYSICAL_TO_LOGICAL = {
  "margin-left": "margin-inline-start",
  "margin-right": "margin-inline-end",
  "margin-top": "margin-block-start",
  "margin-bottom": "margin-block-end",
  "padding-left": "padding-inline-start",
  "padding-right": "padding-inline-end",
  "padding-top": "padding-block-start",
  "padding-bottom": "padding-block-end",
  "border-left": "border-inline-start",
  "border-right": "border-inline-end",
  "border-top": "border-block-start",
  "border-bottom": "border-block-end",
  "border-left-width": "border-inline-start-width",
  "border-right-width": "border-inline-end-width",
  "border-left-color": "border-inline-start-color",
  "border-right-color": "border-inline-end-color",
  "border-top-left-radius": "border-start-start-radius",
  "border-top-right-radius": "border-start-end-radius",
  "border-bottom-left-radius": "border-end-start-radius",
  "border-bottom-right-radius": "border-end-end-radius",
  left: "inset-inline-start",
  right: "inset-inline-end",
  top: "inset-block-start",
  bottom: "inset-block-end",
  float: "float: inline-start | inline-end (or flex/grid)",
  clear: "clear: inline-start | inline-end",
  "text-align: left": "text-align: start",
  "text-align: right": "text-align: end",
};

const bannedProperties = Object.keys(PHYSICAL_TO_LOGICAL).filter((p) => !p.includes(":"));

/** @type {import('stylelint').Config} */
export default {
  extends: ["stylelint-config-standard"],
  rules: {
    // The ban. One entry per property so the message can name the replacement.
    "declaration-property-value-disallowed-list": {
      "text-align": ["/^left$/", "/^right$/"],
      float: ["/^left$/", "/^right$/"],
      clear: ["/^left$/", "/^right$/"],
    },
    "property-disallowed-list": [
      bannedProperties,
      {
        message: (property) =>
          `"${property}" is a physical property and is banned in an RTL-first codebase. ` +
          `Use "${PHYSICAL_TO_LOGICAL[property]}" instead.`,
      },
    ],

    // Tailwind and PostCSS at-rules.
    "at-rule-no-unknown": [
      true,
      {
        ignoreAtRules: ["tailwind", "apply", "layer", "variants", "responsive", "screen", "theme"],
      },
    ],
    // Token values are transcribed verbatim from docs/06 §2 and asserted against
    // that document by apps/web/src/tokens.test.ts. Shortening #FFFFFF to #fff
    // would break the comparison for no benefit.
    "color-hex-length": null,
    "custom-property-pattern": null,
    "selector-class-pattern": null,
    "no-descending-specificity": null,
    "declaration-empty-line-before": null,
    "value-keyword-case": null,
  },
  ignoreFiles: ["**/node_modules/**", "**/.next/**", "**/dist/**"],
};

export { PHYSICAL_TO_LOGICAL };
