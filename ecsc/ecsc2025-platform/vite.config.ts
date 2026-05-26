import {defineConfig} from 'vite'
import {glob} from "glob"
import vue from '@vitejs/plugin-vue'

// https://vitejs.dev/config/
export default defineConfig({
    root: "./mainpage/vite/",
    base: "/static/vite/",
    plugins: [vue()],
    server: {
        port: 5173,
        proxy: {
            "^(?!\/static\/vite/).*": {
                target: "http://localhost:8000",
                changeOrigin: true
            }
        }
    },
    build: {
        outDir: "../../vite_build/",
        manifest: "manifest.json",
        emptyOutDir: true,
        rollupOptions: {
            input: glob.sync("./mainpage/vite/*.ts"),
        },
    },
})

