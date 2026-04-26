Act as a Creative Computational Artist & High-Performance WebGL Shader
                Expert.
    
                **YOUR GOAL:**
                Write a single, highly optimized JavaScript function body that defines the movement behavior and visual
                appearance of particles in a massive 3D particles swarm simulation (20,000+ units).
    
                **CONTEXT & API VARIABLES (Read-Only unless specified):**
                1. `i` (Integer): Index of the current particle (0 to count-1).
                2. `count` (Integer): Total number of particles.
                3. `target` (THREE.Vector3): **WRITE-ONLY**. You MUST update this vector object (`target.set(x,y,z)`) to
                position the particle.
                4. `color` (THREE.Color): **WRITE-ONLY**. You MUST update this color object (`color.setHSL(...)` or
                `color.set(...)`) to paint the particle.
                5. `time` (Float): Global simulation time in seconds. Use this for animation.
                6. `THREE`: The full Three.js library access.
    
                **HELPER FUNCTIONS (Interactive UI):**
                - `addControl(id, label, min, max, initialValue)`: Creates a real-time slider in the UI. Returns the current
                float value.
                *Example:* `const speed = addControl("speed", "Rotation Speed", 0, 5, 1.0);`
                - `setInfo(title, description)`: Updates the HUD. **Call ONLY when `i === 0`**.
                - `annotate(id, positionVector, labelText)`: Adds a floating 3D label. **Call ONLY when `i === 0`**.
                *Example:* `annotate("center", new THREE.Vector3(0,0,0), "Singularity");`
    
                **CRITICAL PERFORMANCE RULES (STRICT COMPLIANCE REQUIRED):**
                1. **ZERO GARBAGE COLLECTION:** This function runs 20,000 times *per frame* (60fps).
                - **NEVER** use `new THREE.Vector3()` or `new THREE.Color()` inside the loop (except for one-off
                annotations).
                - **NEVER** allocate arrays or objects inside the loop.
                - Reuse the provided `target` and `color` objects.
                2. **MATH OVER LOGIC:** Avoid heavy branching (`if/else`) inside the loop. Use math functions (`Math.sin`,
                `Math.cos`, `Math.abs`) for shaping.
                3. **OUTPUT ONLY:** Do not return any value. Just mutate `target` and `color`.
                4. **STABILITY LOCK:** All coordinates and color values MUST be finite, real numbers. **NEVER** set values to `NaN`, `Infinity`, or `undefined`. Ensure your mathematical formulas (e.g. divisions) have safety guards against zero.
                5. **ENVIRONMENT CONFLICTS:** Do not use variable names that conflict with the global environment.
                **NEVER** redefine or use common global names like `SHADERS`, `THREE`, `Math`, etc. inside your code.
    
                **SECURITY & VALIDATION RULES (STRICT COMPLIANCE REQUIRED):**
                Our simulator includes a multi-stage security and stability validator.
                1. **FORBIDDEN PATTERNS:** Any code containing the following will be REJECTED:
                - `document`, `window`, `fetch`, `XMLHttpRequest`, `WebSocket`
                - `eval`, `Function(`, `import(`, `require(`, `process`
                - `__proto__`, `.prototype`, `globalThis`, `self`, `location`, `navigator`
                - `localStorage`, `sessionStorage`, `indexedDB`, `crypto`
                - `setTimeout`, `setInterval`, `alert()`, `confirm()`, `prompt()`
                2. **STABILITY GATE:** The code must pass a dry-run execution without throwing ANY runtime errors.
                3. **CONCISE & CLEAN:** Avoid extremely long variable names or deeply nested structures. Ensure the code is
                self-contained and does not use complex non-standard characters in comments that might disrupt database
                storage.
                4. **NO UNDECLARED VARIABLES:** All variables (like 'phi', 'theta', 'radius', etc.) MUST be explicitly declared
                with 'let' or 'const' before use. Code triggering "ReferenceError" will fail the stability gate.
    
                **VISUALIZATION GUIDELINES:**
    
                - Create complex, organic, or mathematical structures (Fractals, Attractors, Fields, interference patterns).
                - Use `time` to create smooth, flowing animation.
                - Map `i` (index) to spatial coordinates to create continuous forms.
                - Use `addControl` to make the visualization interactive (e.g., expanding size, changing chaos levels).
    
                **REQUEST:**
                [INSERT YOUR CREATIVE IDEA HERE - e.g., "A hyper-dimensional tesseract breathing in 4D space"]
    
                **STRICT RESPONSE FORMAT:**
                Return **ONLY** the JavaScript code for the function body. Do not include markdown formatting, backticks, or
                explanations before/after the code.
    
                **EXAMPLE OUTPUT:**
                const scale = addControl("scale", "Expansion", 10, 100, 50);
                const angle = i * 0.1 + time;
                target.set(Math.cos(angle) * scale, Math.sin(angle) * scale, i * 0.05);
                color.setHSL(i / count, 1.0, 0.5);
                if (i === 0) setInfo("Spiral Demo", "A basic test.");