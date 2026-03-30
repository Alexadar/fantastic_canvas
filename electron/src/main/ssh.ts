/**
 * SSH connection manager — VSCode-style remote connections.
 *
 * Uses the system `ssh` binary to establish port-forwarded tunnels
 * to remote Fantastic servers, exactly like core/instance_backend.py's
 * SSHBackend but driven from the Electron main process.
 */

import { spawn, execFile, type ChildProcess } from "child_process";
import path from "path";
import http from "http";

export interface SSHConnectOptions {
  host: string;
  user: string;
  port: number;
  keyPath?: string;
  backendUrl: string;
}

interface SSHConnection {
  id: string;
  host: string;
  user: string;
  tunnel: ChildProcess;
  localPort: number;
  remotePort: number;
}

export class SSHManager {
  private connections = new Map<string, SSHConnection>();

  /**
   * Connect to a remote host. Steps:
   * 1. Check if fantastic is already running on the remote
   * 2. If not, launch it via ssh
   * 3. Establish an SSH tunnel (local port → remote port)
   * 4. Return the tunneled URL
   */
  async connect(opts: SSHConnectOptions): Promise<{
    localUrl: string;
    remoteHost: string;
    remotePort: number;
  }> {
    const connId = `${opts.user}@${opts.host}:${opts.port}`;
    const existing = this.connections.get(connId);
    if (existing) {
      return {
        localUrl: `http://127.0.0.1:${existing.localPort}`,
        remoteHost: opts.host,
        remotePort: existing.remotePort,
      };
    }

    // 1. Probe remote for existing server
    let remotePort: number | null = null;
    try {
      const configJson = await sshExec(
        opts,
        "cat .fantastic/config.json 2>/dev/null"
      );
      const cfg = JSON.parse(configJson);
      if (cfg.port && cfg.pid) {
        // Verify remote process is alive
        const alive = await sshExec(
          opts,
          `kill -0 ${cfg.pid} 2>/dev/null && echo alive || echo dead`
        );
        if (alive.trim() === "alive") remotePort = cfg.port;
      }
    } catch {
      // No existing server
    }

    // 2. Launch remote server if needed
    if (!remotePort) {
      remotePort = await launchRemote(opts);
    }

    // 3. Find a free local port and tunnel
    const localPort = await findFreePort();

    const sshArgs = [
      "-N", // no remote command, tunnel only
      "-L",
      `${localPort}:127.0.0.1:${remotePort}`,
      "-o",
      "ExitOnForwardFailure=yes",
      "-o",
      "ServerAliveInterval=15",
      "-o",
      "ServerAliveCountMax=3",
      "-o",
      "StrictHostKeyChecking=accept-new",
      "-p",
      String(opts.port),
    ];
    if (opts.keyPath) sshArgs.push("-i", opts.keyPath);
    sshArgs.push(`${opts.user}@${opts.host}`);

    const tunnel = spawn("ssh", sshArgs, { stdio: "ignore" });

    tunnel.on("exit", () => {
      this.connections.delete(connId);
    });

    // Wait for tunnel to be usable
    const localUrl = `http://127.0.0.1:${localPort}`;
    await waitForEndpoint(localUrl, 60);

    const conn: SSHConnection = {
      id: connId,
      host: opts.host,
      user: opts.user,
      tunnel,
      localPort,
      remotePort,
    };
    this.connections.set(connId, conn);

    return { localUrl, remoteHost: opts.host, remotePort };
  }

  disconnectAll(): void {
    for (const conn of this.connections.values()) {
      conn.tunnel.kill("SIGTERM");
    }
    this.connections.clear();
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function sshExec(
  opts: SSHConnectOptions,
  command: string
): Promise<string> {
  return new Promise((resolve, reject) => {
    const args = [
      "-o", "BatchMode=yes",
      "-o", "ConnectTimeout=10",
      "-p", String(opts.port),
    ];
    if (opts.keyPath) args.push("-i", opts.keyPath);
    args.push(`${opts.user}@${opts.host}`, command);

    execFile("ssh", args, { timeout: 15_000 }, (err, stdout) => {
      if (err) reject(err);
      else resolve(stdout);
    });
  });
}

async function findFreePort(): Promise<number> {
  const { createServer } = await import("net");
  return new Promise((resolve, reject) => {
    const srv = createServer();
    srv.listen(0, "127.0.0.1", () => {
      const addr = srv.address();
      if (addr && typeof addr !== "string") {
        const port = addr.port;
        srv.close(() => resolve(port));
      } else {
        reject(new Error("Could not find a free port"));
      }
    });
    srv.on("error", reject);
  });
}

/** Launch `fantastic serve` on the remote host, return the remote port. */
async function launchRemote(opts: SSHConnectOptions): Promise<number> {
  // Try `fantastic serve` first (globally installed), fallback to `uv run fantastic serve`
  const cmds = [
    "fantastic serve --port 0",
    "uv run fantastic serve --port 0",
    "python3 -m core.cli serve --port 0",
  ];

  for (const cmd of cmds) {
    try {
      // Launch in background, read config
      await sshExec(opts, `nohup ${cmd} > /dev/null 2>&1 & sleep 3`);
      const configJson = await sshExec(
        opts,
        "cat .fantastic/config.json 2>/dev/null"
      );
      const cfg = JSON.parse(configJson);
      if (cfg.port) return cfg.port;
    } catch {
      continue;
    }
  }

  throw new Error(
    `Could not start fantastic on ${opts.host}. ` +
      "Ensure Python 3.11+ and fantastic are installed on the remote."
  );
}

function waitForEndpoint(
  url: string,
  maxRetries: number
): Promise<void> {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    const check = () => {
      http
        .get(`${url}/api/state`, (res) => {
          if (res.statusCode === 200) resolve();
          else if (++attempts < maxRetries) setTimeout(check, 500);
          else reject(new Error(`Endpoint ${url} not ready after ${maxRetries} retries`));
        })
        .on("error", () => {
          if (++attempts < maxRetries) setTimeout(check, 500);
          else reject(new Error(`Endpoint ${url} not reachable after ${maxRetries} retries`));
        });
    };
    check();
  });
}

