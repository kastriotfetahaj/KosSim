var _a;
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
var BACKEND = (_a = process.env.KOSSIM_BACKEND) !== null && _a !== void 0 ? _a : "http://127.0.0.1:8000";
export default defineConfig({
    plugins: [react()],
    server: {
        port: 5173,
        proxy: {
            "/api": { target: BACKEND, changeOrigin: true },
            "/admin": { target: BACKEND, changeOrigin: true },
            "/static": { target: BACKEND, changeOrigin: true },
            "/health": { target: BACKEND, changeOrigin: true },
        },
    },
    build: {
        outDir: "dist",
        emptyOutDir: true,
    },
});
