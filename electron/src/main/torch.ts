/**
 * Detect whether PyTorch is available in the target Python environment.
 * If not, the app runs in "noai" mode — canvas still works, but no local
 * AI inference. Users can still configure external AI via .fantastic/.
 */

import { execFile } from "child_process";

export interface TorchStatus {
  available: boolean;
  version?: string;
  device?: string; // "cpu", "mps", "cuda"
}

export async function detectTorch(
  pythonPath: string
): Promise<TorchStatus> {
  const script = `
import json, sys
try:
    import torch
    device = "cpu"
    if torch.backends.mps.is_available():
        device = "mps"
    elif torch.cuda.is_available():
        device = "cuda"
    json.dump({"available": True, "version": torch.__version__, "device": device}, sys.stdout)
except ImportError:
    json.dump({"available": False}, sys.stdout)
`;

  return new Promise((resolve) => {
    execFile(
      pythonPath,
      ["-c", script],
      { timeout: 10_000 },
      (err, stdout) => {
        if (err) {
          resolve({ available: false });
          return;
        }
        try {
          resolve(JSON.parse(stdout));
        } catch {
          resolve({ available: false });
        }
      }
    );
  });
}
