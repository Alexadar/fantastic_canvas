import type { ForgeConfig } from "@electron-forge/shared-types";
import { MakerDMG } from "@electron-forge/maker-dmg";
import { MakerZIP } from "@electron-forge/maker-zip";
import { VitePlugin } from "@electron-forge/plugin-vite";
import path from "path";

const config: ForgeConfig = {
  packagerConfig: {
    name: "Fantastic Canvas",
    executableName: "fantastic-canvas",
    icon: path.resolve(__dirname, "resources/icons/icon"),
    asar: true,
    // macOS code signing — all creds come from environment, never from git.
    // Set these in your shell or CI:
    //   APPLE_IDENTITY          – "Developer ID Application: ..."
    //   APPLE_ID                – your Apple ID email
    //   APPLE_PASSWORD          – app-specific password
    //   APPLE_TEAM_ID           – 10-char team ID
    //   KEYCHAIN_PROFILE        – or use notarytool stored credentials
    osxSign: process.env.APPLE_IDENTITY
      ? {
          identity: process.env.APPLE_IDENTITY,
          optionsForFile: () => ({
            entitlements: path.resolve(
              __dirname,
              "mac/entitlements.plist"
            ),
            "entitlements-inherit": path.resolve(
              __dirname,
              "mac/entitlements.inherit.plist"
            ),
          }),
        }
      : undefined,
    osxNotarize: process.env.APPLE_ID
      ? {
          appleId: process.env.APPLE_ID,
          appleIdPassword: process.env.APPLE_PASSWORD ?? "",
          teamId: process.env.APPLE_TEAM_ID ?? "",
        }
      : process.env.KEYCHAIN_PROFILE
        ? { keychainProfile: process.env.KEYCHAIN_PROFILE }
        : undefined,
    extraResource: [
      // The Python core package is resolved at runtime — not bundled here.
      // See src/main/backend.ts for discovery logic.
    ],
  },

  makers: [
    new MakerZIP({}, ["darwin"]),
    new MakerDMG({
      format: "ULFO",
      icon: path.resolve(__dirname, "resources/icons/icon.icns"),
    }),
  ],

  plugins: [
    new VitePlugin({
      build: [
        {
          entry: "src/main/index.ts",
          config: "vite.main.config.ts",
          target: "main",
        },
        {
          entry: "src/main/preload.ts",
          config: "vite.preload.config.ts",
          target: "preload",
        },
      ],
      renderer: [
        {
          name: "main_window",
          config: "vite.renderer.config.ts",
        },
      ],
    }),
  ],
};

export default config;
