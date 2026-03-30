/**
 * Fantastic Canvas — Electron main process.
 *
 * Lifecycle:
 *   1. Detect Python + torch availability
 *   2. Launch the fantastic backend in a .fantastic subfolder
 *   3. Open a BrowserWindow pointing at the backend
 *   4. Expose IPC for view switching (canvas ↔ stdio) and SSH connections
 */

import {
  app,
  BrowserWindow,
  ipcMain,
  Menu,
  dialog,
  nativeTheme,
} from "electron";
import path from "path";
import { BackendProcess, discoverPython } from "./backend";
import { detectTorch, type TorchStatus } from "./torch";
import { SSHManager } from "./ssh";

// Squirrel install/update hooks (Windows — no-op on macOS but safe to import)
// eslint-disable-next-line @typescript-eslint/no-require-imports
if (require("electron-squirrel-startup")) app.quit();

// ---------------------------------------------------------------------------
// Globals
// ---------------------------------------------------------------------------

let mainWindow: BrowserWindow | null = null;
let backend: BackendProcess | null = null;
let sshManager: SSHManager | null = null;
let torchStatus: TorchStatus = { available: false };

/** Current view: "canvas" (web UI) or "stdio" (terminal conversation) */
let currentView: "canvas" | "stdio" = "canvas";

// Working directory — default to where the app was launched, or home.
const projectDir =
  process.env.FANTASTIC_PROJECT_DIR || process.cwd();

// ---------------------------------------------------------------------------
// Window
// ---------------------------------------------------------------------------

function createWindow(backendUrl: string): BrowserWindow {
  const preloadPath = path.join(__dirname, "preload.js");

  const win = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 800,
    minHeight: 600,
    title: "Fantastic Canvas",
    titleBarStyle: "hiddenInset", // macOS native look
    trafficLightPosition: { x: 12, y: 12 },
    backgroundColor: nativeTheme.shouldUseDarkColors
      ? "#1a1a2e"
      : "#ffffff",
    webPreferences: {
      preload: preloadPath,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  // Start with canvas view
  win.loadURL(backendUrl);

  win.on("closed", () => {
    mainWindow = null;
  });

  return win;
}

// ---------------------------------------------------------------------------
// Menu (includes view toggle + SSH)
// ---------------------------------------------------------------------------

function buildMenu(backendUrl: string): void {
  const template: Electron.MenuItemConstructorOptions[] = [
    {
      label: "Fantastic Canvas",
      submenu: [
        { role: "about" },
        { type: "separator" },
        {
          label: "Preferences…",
          accelerator: "CmdOrCtrl+,",
          click: () => mainWindow?.webContents.send("open-preferences"),
        },
        { type: "separator" },
        { role: "hide" },
        { role: "hideOthers" },
        { role: "unhide" },
        { type: "separator" },
        { role: "quit" },
      ],
    },
    {
      label: "View",
      submenu: [
        {
          label: "Canvas",
          accelerator: "CmdOrCtrl+1",
          click: () => switchView("canvas", backendUrl),
        },
        {
          label: "Terminal (stdio)",
          accelerator: "CmdOrCtrl+2",
          click: () => switchView("stdio", backendUrl),
        },
        { type: "separator" },
        { role: "reload" },
        { role: "forceReload" },
        { role: "toggleDevTools" },
        { type: "separator" },
        { role: "togglefullscreen" },
      ],
    },
    {
      label: "Connection",
      submenu: [
        {
          label: "Connect via SSH…",
          accelerator: "CmdOrCtrl+Shift+S",
          click: () => mainWindow?.webContents.send("ssh-connect-dialog"),
        },
        {
          label: "Disconnect Remote",
          click: () => {
            sshManager?.disconnectAll();
            mainWindow?.webContents.send("ssh-disconnected");
          },
        },
      ],
    },
    { label: "Edit", submenu: [
      { role: "undo" }, { role: "redo" }, { type: "separator" },
      { role: "cut" }, { role: "copy" }, { role: "paste" },
      { role: "selectAll" },
    ]},
    { label: "Window", submenu: [
      { role: "minimize" }, { role: "zoom" }, { role: "close" },
    ]},
  ];

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

// ---------------------------------------------------------------------------
// View switching
// ---------------------------------------------------------------------------

function switchView(
  view: "canvas" | "stdio",
  backendUrl: string
): void {
  if (!mainWindow || currentView === view) return;
  currentView = view;

  if (view === "canvas") {
    mainWindow.loadURL(backendUrl);
  } else {
    // stdio view — a lightweight terminal UI served by the backend
    mainWindow.loadURL(`${backendUrl}/api/state`).then(() => {
      // For now, load a minimal terminal page. The renderer will create
      // an xterm.js instance connected to the backend's WS.
      mainWindow?.webContents.send("switch-view", "stdio");
    });
    mainWindow.loadURL(
      `data:text/html,${encodeURIComponent(stdioShell(backendUrl))}`
    );
  }

  mainWindow.webContents.send("view-changed", view);
}

/** Minimal HTML shell for the stdio/terminal view. */
function stdioShell(backendUrl: string): string {
  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Fantastic — Terminal</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      background: #1a1a2e; color: #e0e0e0;
      font-family: "SF Mono", "Menlo", "Monaco", monospace;
      font-size: 14px; padding: 12px;
      height: 100vh; display: flex; flex-direction: column;
    }
    #toolbar {
      display: flex; align-items: center; gap: 8px;
      padding: 6px 0; margin-bottom: 8px; border-bottom: 1px solid #333;
    }
    #toolbar button {
      background: #2a2a4a; color: #e0e0e0; border: 1px solid #444;
      border-radius: 4px; padding: 4px 12px; cursor: pointer; font-size: 12px;
    }
    #toolbar button:hover { background: #3a3a5a; }
    #toolbar .mode { color: #888; font-size: 11px; }
    #output {
      flex: 1; overflow-y: auto; white-space: pre-wrap; word-break: break-all;
      padding: 8px; background: #111; border-radius: 4px;
    }
    #input-row { display: flex; gap: 8px; margin-top: 8px; }
    #input-row input {
      flex: 1; background: #222; color: #e0e0e0; border: 1px solid #444;
      border-radius: 4px; padding: 6px 10px; font-family: inherit; font-size: 14px;
      outline: none;
    }
    #input-row input:focus { border-color: #7c3aed; }
    .msg-core { color: #d946ef; }
    .msg-user { color: #4ade80; }
    .msg-agent { color: #22d3ee; }
  </style>
</head>
<body>
  <div id="toolbar">
    <button id="btn-canvas" title="Switch to Canvas (Cmd+1)">Canvas View</button>
    <span class="mode" id="mode-label">stdio</span>
  </div>
  <div id="output"></div>
  <div id="input-row">
    <input id="cmd" placeholder="Type a command…" autofocus />
  </div>
  <script>
    const API = "${backendUrl}";
    const out = document.getElementById("output");
    const cmd = document.getElementById("cmd");

    // Switch back to canvas via IPC
    document.getElementById("btn-canvas").addEventListener("click", () => {
      window.electronAPI?.switchView("canvas");
    });

    // Connect WS
    const ws = new WebSocket(API.replace(/^http/, "ws") + "/ws");
    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        if (msg.type === "conversation") {
          const span = document.createElement("span");
          const who = msg.who || "system";
          span.className =
            who === "user" ? "msg-user" :
            who === "core" || who === "system" ? "msg-core" : "msg-agent";
          span.textContent = who + ": " + msg.text + "\\n";
          out.appendChild(span);
          out.scrollTop = out.scrollHeight;
        }
      } catch {}
    };

    // Load conversation history
    fetch(API + "/api/call", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tool: "get_state", args: {} }),
    })
    .then(r => r.json())
    .then(state => {
      if (state?.conversation) {
        state.conversation.forEach(line => {
          const span = document.createElement("span");
          span.textContent = line + "\\n";
          out.appendChild(span);
        });
        out.scrollTop = out.scrollHeight;
      }
    })
    .catch(() => {});

    // Send commands
    cmd.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && cmd.value.trim()) {
        const text = cmd.value.trim();
        cmd.value = "";
        ws.send(JSON.stringify({ type: "command", text }));
      }
    });
  </script>
</body>
</html>`;
}

// ---------------------------------------------------------------------------
// IPC handlers
// ---------------------------------------------------------------------------

function registerIPC(backendUrl: string): void {
  ipcMain.handle("get-backend-url", () => backendUrl);
  ipcMain.handle("get-torch-status", () => torchStatus);
  ipcMain.handle("get-current-view", () => currentView);
  ipcMain.handle("get-project-dir", () => projectDir);

  ipcMain.handle("switch-view", (_e, view: "canvas" | "stdio") => {
    switchView(view, backendUrl);
  });

  ipcMain.handle(
    "ssh-connect",
    async (_e, opts: { host: string; user?: string; keyPath?: string; port?: number }) => {
      if (!sshManager) sshManager = new SSHManager();
      try {
        const info = await sshManager.connect({
          host: opts.host,
          user: opts.user || "root",
          keyPath: opts.keyPath,
          port: opts.port || 22,
          backendUrl,
        });
        return { ok: true, ...info };
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        return { ok: false, error: msg };
      }
    }
  );

  ipcMain.handle("ssh-disconnect", () => {
    sshManager?.disconnectAll();
    return { ok: true };
  });
}

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------

app.whenReady().then(async () => {
  // 1. Discover Python
  const pythonPath = await discoverPython();
  if (!pythonPath) {
    dialog.showErrorBox(
      "Python not found",
      "Fantastic Canvas requires Python 3.11+.\n\n" +
        "Install via: brew install python@3.11\n" +
        "Or: https://www.python.org/downloads/"
    );
    app.quit();
    return;
  }

  // 2. Detect torch
  torchStatus = await detectTorch(pythonPath);
  console.log(
    `[fantastic] torch: ${torchStatus.available ? "yes" : "no (noai mode)"}` +
      (torchStatus.version ? ` v${torchStatus.version}` : "")
  );

  // 3. Launch backend
  backend = new BackendProcess(pythonPath, projectDir);
  let backendUrl: string;
  try {
    backendUrl = await backend.start();
  } catch (err) {
    dialog.showErrorBox(
      "Backend failed to start",
      `Could not start the Fantastic server.\n\n${err}`
    );
    app.quit();
    return;
  }
  console.log(`[fantastic] backend ready at ${backendUrl}`);

  // 4. Create window
  mainWindow = createWindow(backendUrl);
  buildMenu(backendUrl);
  registerIPC(backendUrl);

  // macOS: re-open window on dock click
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      mainWindow = createWindow(backendUrl);
    }
  });
});

app.on("window-all-closed", () => {
  backend?.stop();
  sshManager?.disconnectAll();
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  backend?.stop();
  sshManager?.disconnectAll();
});
