import { Kernel } from "./kernel/kernel.ts";
import { Agent } from "./kernel/agent.ts";
import { WsBridge } from "./transport/bridge.ts";
import { ProxyLoader } from "./bundles/loader/proxy_loader.ts";
import { registerGlAgent } from "./bundles/gl_agent/gl_agent.ts";
import { registerHtmlAgent } from "./bundles/html_agent/html_agent.ts";
import { mountCanvas } from "./bundles/canvas/canvas.ts";

// The frontend kernel boots as a PEER of the host. It dials the host's
// `web_loader` alias over the bridge (a host-side `fs_loader` rooted at
// `.fantastic/web/`, which the operator created — no automation), hydrates its
// OWN agent tree from there (`load_tree`), and persists every local change back
// (`proxy_loader`). The canvas renders the LOCAL member tree; host backends are
// weak peers referenced by id. One shared frontend tree, addressed by alias —
// no per-session id.

const LOADER = "web_loader"; // the host-side web/fs_loader alias
const origin =
  (location.protocol === "https:" ? "wss://" : "ws://") + location.host;

const kernel = new Kernel();
// Register the JS bundles whose records this kernel runs locally. Anything
// else (e.g. a `*.tools` host record that strays in) weak-loads + skips.
registerGlAgent(kernel);
registerHtmlAgent(kernel);
kernel.registerBundle("canvas.ts", () => null); // the compositor root (rendered, not a verb agent)
// View bundles that front a host backend are real frontend agents too — a
// no-op handler makes their records load-able; the ViewBundle renders them.
kernel.registerBundle("terminal_view.ts", () => null);
kernel.registerBundle("ai_view.ts", () => null);

new WsBridge(kernel, { origin, controlEndpoint: LOADER });
// The ONE auto-added agent in the JS runtime — its single autoagent (the loader),
// mirroring the host root loader. Everything else below is explicit.
const loader = new ProxyLoader(kernel, LOADER);

const records = await loader.loadTree();
if (records.length === 0) {
  // Fresh: seed the canvas root — the operator's first conscious agent.
  kernel.setRoot(
    new Agent({
      id: "canvas",
      handlerModule: "canvas.ts",
      sentence: "Canvas compositor — renders the frontend's own member tree.",
    }),
  );
} else {
  kernel.load(records);
}
loader.start(); // watch the local tree → persist/forget over the bridge

await mountCanvas({ kernel, mount: document.body, selfId: kernel.rootId ?? "canvas" });
