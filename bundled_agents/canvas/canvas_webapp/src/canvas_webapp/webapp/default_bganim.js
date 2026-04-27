// Default canvas bganim — neon-magenta volumetric "FANTASTIC" + 80s Tron grid.
// Per-particle function body; see ./bganim.md for the API contract.
// Parameters hard-coded (no addControl) — bg is bg, not a control panel.

// ── 5x7 bitmap font sampled offline → 132 lit pixels for "FANTASTIC".
// Centered around origin. x ∈ [-26, 26], y ∈ [-3, 3].
const TPTS = [
  -26,3,-26,2,-26,1,-26,0,-26,-1,-26,-2,-26,-3,-25,3,-25,0,-24,3,-24,0,
  -23,3,-23,0,-22,3,-20,2,-20,1,-20,0,-20,-1,-20,-2,-20,-3,-19,3,-19,0,
  -18,3,-18,0,-17,3,-17,0,-16,2,-16,1,-16,0,-16,-1,-16,-2,-16,-3,-14,3,
  -14,2,-14,1,-14,0,-14,-1,-14,-2,-14,-3,-13,2,-12,1,-11,0,-10,3,-10,2,
  -10,1,-10,0,-10,-1,-10,-2,-10,-3,-8,3,-7,3,-6,3,-6,2,-6,1,-6,0,-6,-1,
  -6,-2,-6,-3,-5,3,-4,3,-2,2,-2,1,-2,0,-2,-1,-2,-2,-2,-3,-1,3,-1,0,
  0,3,0,0,1,3,1,0,2,2,2,1,2,0,2,-1,2,-2,2,-3,4,2,4,1,4,-3,5,3,5,0,5,-3,
  6,3,6,0,6,-3,7,3,7,0,7,-3,8,3,8,-1,8,-2,10,3,11,3,12,3,12,2,12,1,12,0,
  12,-1,12,-2,12,-3,13,3,14,3,16,3,16,-3,17,3,17,-3,18,3,18,2,18,1,18,0,
  18,-1,18,-2,18,-3,19,3,19,-3,20,3,20,-3,22,2,22,1,22,0,22,-1,22,-2,
  23,3,23,-3,24,3,24,-3,25,3,25,-3,26,2,26,-2,
];
const TPTS_N = 132;

// ── allocation: 60% of particles paint the text, 40% paint the floor grid.
const NT = (count * 0.6) | 0;
const SCALE = 3.2;           // text size multiplier (text spans ~166 world units)
const FLOOR_Y = -18;         // grid plane y (just below text baseline)
const FLOOR_HALF_X = 110;    // grid extends ±110 in x (wider than text)
const FLOOR_DEPTH = 220;     // z extent toward horizon
const SCROLL = 0.6;          // forward scroll speed of grid (Tron retreat)

if (i < NT) {
  // Text particle: pick a lit pixel cluster, jitter for swarm feel,
  // breathe on z so the word reads as 3D volumetric neon.
  const ti = (i % TPTS_N) * 2;
  const tx = TPTS[ti] * SCALE;
  const ty = TPTS[ti + 1] * SCALE;
  // Per-particle deterministic jitter (no Math.random — repeatable each frame).
  const jx = Math.sin(i * 12.9898 + time * 0.3) * 1.4;
  const jy = Math.cos(i * 78.233 + time * 0.4) * 1.4;
  const jz = Math.sin(i * 4.1 + time * 0.6) * 4.0;
  const breathe = Math.sin(time * 0.8 + tx * 0.05) * 2.5;
  target.set(tx + jx, ty + jy + 1.5, jz + breathe);
  // Magenta core, slight hue drift toward cyan along x for depth read.
  const hue = 0.86 + tx * 0.0006 + Math.sin(time * 0.4) * 0.03;
  color.setHSL(((hue % 1) + 1) % 1, 1.0, 0.55);
} else {
  // Floor grid particle. Distribute on a regular lattice on the y=FLOOR_Y plane.
  // Lattice spacing chosen so points read as Tron-grid intersections.
  const k = i - NT;
  const COLS = 60;             // ~3K particles → 60 cols × 50 rows
  const cx = (k % COLS) - (COLS / 2);
  const cz = ((k / COLS) | 0);
  const stepX = (FLOOR_HALF_X * 2) / COLS;
  const gx = cx * stepX + stepX * 0.5;
  // Scroll z forward; wrap when crossing the camera (z > 30).
  let gz = cz * 6 - ((time * SCROLL * 60) % FLOOR_DEPTH);
  if (gz > 30) gz -= FLOOR_DEPTH;
  if (gz < 30 - FLOOR_DEPTH) gz += FLOOR_DEPTH;
  // Subtle bobble so the grid reads as alive without breaking the lattice.
  const bob = Math.sin(time * 1.2 + cx * 0.4 + cz * 0.3) * 0.4;
  target.set(gx, FLOOR_Y + bob, gz);
  // Hot magenta near camera, fading to deep purple at horizon.
  const depth = Math.max(0, Math.min(1, (30 - gz) / FLOOR_DEPTH));
  const hue = 0.86;
  color.setHSL(hue, 1.0, 0.55 - depth * 0.4);
}
