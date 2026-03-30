/**
 * Renderer entry — minimal bootstrap.
 * The actual canvas UI is loaded from the backend (BrowserWindow.loadURL).
 * This file handles the Electron-specific chrome: view-switch button,
 * torch status indicator, and SSH connection dialog.
 */

declare global {
  interface Window {
    electronAPI: {
      getBackendUrl: () => Promise<string>;
      getTorchStatus: () => Promise<{
        available: boolean;
        version?: string;
        device?: string;
      }>;
      getProjectDir: () => Promise<string>;
      getCurrentView: () => Promise<"canvas" | "stdio">;
      switchView: (view: "canvas" | "stdio") => Promise<void>;
      sshConnect: (opts: {
        host: string;
        user?: string;
        keyPath?: string;
        port?: number;
      }) => Promise<{ ok: boolean; localUrl?: string; error?: string }>;
      sshDisconnect: () => Promise<{ ok: boolean }>;
      onViewChanged: (cb: (view: string) => void) => void;
      onSSHConnectDialog: (cb: () => void) => void;
      onSSHDisconnected: (cb: () => void) => void;
    };
  }
}

async function init() {
  const api = window.electronAPI;
  if (!api) return; // not running in Electron

  const torch = await api.getTorchStatus();
  console.log(
    `[fantastic] torch: ${torch.available ? `v${torch.version} (${torch.device})` : "unavailable — noai mode"}`
  );

  // Listen for SSH connect dialog trigger from menu
  api.onSSHConnectDialog(() => {
    const host = prompt("SSH host (user@host):");
    if (!host) return;

    const [user, hostname] = host.includes("@")
      ? host.split("@", 2)
      : ["root", host];

    api.sshConnect({ host: hostname, user }).then((result) => {
      if (result.ok) {
        alert(`Connected to ${hostname}\nLocal URL: ${result.localUrl}`);
      } else {
        alert(`SSH failed: ${result.error}`);
      }
    });
  });
}

init();

export {};
