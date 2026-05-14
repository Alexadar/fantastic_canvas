# canvas_webapp — spatial UI
The infinite-canvas browser UI. Owns a canvas_backend child (auto-created on boot, tracked via `upstream_id`). `get_webapp` → iframe descriptor.

Zoom is **horizon-anchored**: the wheel pulls toward/away from screen center, not the cursor. The 2D iframe layer and the GL scene scale around that one shared point and stay in sync (`camera.zoom` follows the CSS `view.z`) — pure proportional zoom, no dolly/slide. 2D HTML panes live on the depth-0 plane and zoom as the main camera; GL content keeps its depth parallax around the same locked plane.
