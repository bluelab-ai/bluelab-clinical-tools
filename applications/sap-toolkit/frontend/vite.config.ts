import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    allowedHosts: true,
    hmr: false,
    proxy: {
      "/api": {
        target: "http://localhost:8000/",
        changeOrigin: true,
        timeout: 0,       // 禁用代理超时，SSE 长连接需要
        proxyTimeout: 0,   // 禁用后端响应超时
      },
    },
  },
});
