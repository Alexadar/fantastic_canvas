/**
 * Preload script — exposes a safe electronAPI to the renderer
 * via contextBridge. No Node.js access leaks to the web content.
 */

import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("electronAPI", {
  // Backend
  getBackendUrl: () => ipcRenderer.invoke("get-backend-url"),
  getTorchStatus: () => ipcRenderer.invoke("get-torch-status"),
  getProjectDir: () => ipcRenderer.invoke("get-project-dir"),

  // View switching
  getCurrentView: () => ipcRenderer.invoke("get-current-view"),
  switchView: (view: "canvas" | "stdio") =>
    ipcRenderer.invoke("switch-view", view),

  // SSH
  sshConnect: (opts: {
    host: string;
    user?: string;
    keyPath?: string;
    port?: number;
  }) => ipcRenderer.invoke("ssh-connect", opts),
  sshDisconnect: () => ipcRenderer.invoke("ssh-disconnect"),

  // Events from main → renderer
  onViewChanged: (cb: (view: string) => void) =>
    ipcRenderer.on("view-changed", (_e, view) => cb(view)),
  onSSHConnectDialog: (cb: () => void) =>
    ipcRenderer.on("ssh-connect-dialog", () => cb()),
  onSSHDisconnected: (cb: () => void) =>
    ipcRenderer.on("ssh-disconnected", () => cb()),
});
