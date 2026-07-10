// Generates the Material 3 color tokens in src/index.css.
// Run: node scripts/gen-m3-tokens.mjs
// The scheme is HCT-derived from one seed via the official
// @material/material-color-utilities, with success/warning as M3 custom
// colors harmonized toward the seed. Paste the output into src/index.css
// whenever the seed changes; do not hand-edit individual hex values.

import {
  themeFromSourceColor,
  argbFromHex,
  hexFromArgb,
} from "@material/material-color-utilities";

const SEED = "#0B57D0"; // deep product blue: trust/audit, deliberately not violet
const CUSTOM = [
  { name: "success", value: argbFromHex("#1E8E3E"), blend: true },
  { name: "warning", value: argbFromHex("#E37400"), blend: true },
];

const theme = themeFromSourceColor(argbFromHex(SEED), CUSTOM);

// M3 surface-container roles come from the neutral palette tones.
const SURFACE_TONES = {
  light: {
    surface: 98,
    "surface-dim": 87,
    "surface-bright": 98,
    "surface-container-lowest": 100,
    "surface-container-low": 96,
    "surface-container": 94,
    "surface-container-high": 92,
    "surface-container-highest": 90,
  },
  dark: {
    surface: 6,
    "surface-dim": 6,
    "surface-bright": 24,
    "surface-container-lowest": 4,
    "surface-container-low": 10,
    "surface-container": 12,
    "surface-container-high": 17,
    "surface-container-highest": 22,
  },
};

const kebab = (s) => s.replace(/([A-Z])/g, "-$1").toLowerCase();

function block(mode) {
  const scheme = theme.schemes[mode].toJSON();
  const lines = [];
  for (const [role, argb] of Object.entries(scheme)) {
    if (role in SURFACE_TONES[mode]) continue; // new-spec tone wins
    lines.push(`  --md-${kebab(role)}: ${hexFromArgb(argb)};`);
  }
  for (const [role, tone] of Object.entries(SURFACE_TONES[mode])) {
    lines.push(`  --md-${role}: ${hexFromArgb(theme.palettes.neutral.tone(tone))};`);
  }
  for (const custom of theme.customColors) {
    const group = custom[mode];
    const n = custom.color.name;
    lines.push(`  --md-${n}: ${hexFromArgb(group.color)};`);
    lines.push(`  --md-on-${n}: ${hexFromArgb(group.onColor)};`);
    lines.push(`  --md-${n}-container: ${hexFromArgb(group.colorContainer)};`);
    lines.push(`  --md-on-${n}-container: ${hexFromArgb(group.onColorContainer)};`);
  }
  return lines.sort().join("\n");
}

console.log(`/* seed ${SEED} */`);
console.log(":root {\n" + block("light") + "\n}");
console.log('\n:root[data-theme="dark"] {\n' + block("dark") + "\n}");
