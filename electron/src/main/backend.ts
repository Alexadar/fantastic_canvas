/**
 * Python backend lifecycle — discover Python, launch `fantastic serve`,
 * wait for the HTTP health endpoint, and tear down on quit.
 */

import { spawn, execFile, type ChildProcess } from "child_process";
import path from "path";
import fs from "fs";
import http from "http";

// ---------------------------------------------------------------------------
// Python discovery
// ---------------------------------------------------------------------------

/** Find a usable Python 3.11+ interpreter. */
export async function discoverPython(): Promise<string | null> {
  // Priority: explicit env var > uv-managed > common names
  const candidates = [
    process.env.FANTASTIC_PYTHON,
    // If we're in a dev checkout, try the uv venv
    path.resolve(process.cwd(), ".venv/bin/python"),
    "python3",
    "python",
    "/usr/local/bin/python3",
    "/opt/homebrew/bin/python3",
  ].filter(Boolean) as string[];

  for (const candidate of candidates) {
    try {
      const version = await execAsync(candidate, [
        "-c",
        "import sys; v=sys.version_info; print(f'{v.major}.{v.minor}')",
      ]);
      const [major, minor] = version.trim().split(".").map(Number);
      if (major >= 3 && minor >= 11) return candidate;
    } catch {
      // not found or wrong version
    }
  }
  return null;
}

function execAsync(cmd: string, args: string[]): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile(cmd, args, { timeout: 5000 }, (err, stdout) => {
      if (err) reject(err);
      else resolve(stdout);
    });
  });
}

// ---------------------------------------------------------------------------
// Backend process
// ---------------------------------------------------------------------------

export class BackendProcess {
  private proc: ChildProcess | null = null;
  private url = "";

  constructor(
    private pythonPath: string,
    private projectDir: string
  ) {}

  /** Start `fantastic serve` and return the backend URL once healthy. */
  async start(): Promise<string> {
    // Ensure .fantastic dir exists
    const dotDir = path.join(this.projectDir, ".fantastic");
    if (!fs.existsSync(dotDir)) {
      fs.mkdirSync(dotDir, { recursive: true });
    }

    // Check if a server is already running (singleton detection)
    const configPath = path.join(dotDir, "config.json");
    if (fs.existsSync(configPath)) {
      try {
        const cfg = JSON.parse(fs.readFileSync(configPath, "utf-8"));
        if (cfg.port && cfg.pid && isProcessAlive(cfg.pid)) {
          const existing = `http://127.0.0.1:${cfg.port}`;
          const alive = await this.healthCheck(existing, 3);
          if (alive) {
            this.url = existing;
            console.log(
              `[backend] reusing existing server pid=${cfg.pid} port=${cfg.port}`
            );
            return this.url;
          }
        }
      } catch {
        // corrupt config — launch fresh
      }
    }

    return new Promise<string>((resolve, reject) => {
      // Launch: python -m core.cli serve --project-dir <dir>
      // The backend auto-picks a port and writes it to config.json.
      const args = [
        "-m",
        "core.cli",
        "serve",
        "--project-dir",
        this.projectDir,
      ];

      this.proc = spawn(this.pythonPath, args, {
        cwd: this.projectDir,
        stdio: ["ignore", "pipe", "pipe"],
        env: {
          ...process.env,
          // Ensure the core package is importable from the project root
          PYTHONPATH: this.projectDir,
        },
      });

      let output = "";

      this.proc.stdout?.on("data", (chunk: Buffer) => {
        const text = chunk.toString();
        output += text;
        console.log(`[backend:stdout] ${text.trim()}`);

        // Look for the "Uvicorn running on http://..." line
        const match = text.match(/running on (https?:\/\/[\d.:]+)/i);
        if (match) {
          this.url = match[1].replace("0.0.0.0", "127.0.0.1");
          this.waitHealthy(this.url)
            .then(() => resolve(this.url))
            .catch(reject);
        }
      });

      this.proc.stderr?.on("data", (chunk: Buffer) => {
        const text = chunk.toString();
        output += text;
        console.log(`[backend:stderr] ${text.trim()}`);

        // uvicorn logs to stderr
        const match = text.match(/running on (https?:\/\/[\d.:]+)/i);
        if (match) {
          this.url = match[1].replace("0.0.0.0", "127.0.0.1");
          this.waitHealthy(this.url)
            .then(() => resolve(this.url))
            .catch(reject);
        }
      });

      this.proc.on("exit", (code) => {
        if (!this.url) {
          reject(
            new Error(
              `Backend exited with code ${code} before becoming ready.\n${output.slice(-500)}`
            )
          );
        }
      });

      // Timeout: if no URL detected in 30s, reject
      setTimeout(() => {
        if (!this.url) {
          reject(
            new Error(
              "Backend did not start within 30 seconds.\n" + output.slice(-500)
            )
          );
        }
      }, 30_000);
    });
  }

  /** Graceful stop. */
  stop(): void {
    if (this.proc && !this.proc.killed) {
      this.proc.kill("SIGTERM");
      // Escalate after 3s
      setTimeout(() => {
        if (this.proc && !this.proc.killed) {
          this.proc.kill("SIGKILL");
        }
      }, 3000);
    }
  }

  private async waitHealthy(
    url: string,
    retries = 30
  ): Promise<void> {
    for (let i = 0; i < retries; i++) {
      if (await this.healthCheck(url, 1)) return;
      await sleep(500);
    }
    throw new Error(`Backend at ${url} did not become healthy`);
  }

  private healthCheck(
    url: string,
    retries: number
  ): Promise<boolean> {
    return new Promise((resolve) => {
      let attempts = 0;
      const check = () => {
        http
          .get(`${url}/api/state`, (res) => {
            if (res.statusCode === 200) resolve(true);
            else if (++attempts < retries) setTimeout(check, 300);
            else resolve(false);
          })
          .on("error", () => {
            if (++attempts < retries) setTimeout(check, 300);
            else resolve(false);
          });
      };
      check();
    });
  }
}

function isProcessAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}
