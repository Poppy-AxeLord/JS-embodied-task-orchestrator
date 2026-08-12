// Vite 构建与开发服务器配置
// 说明：
// 1) 使用官方 @vitejs/plugin-vue 插件支持 Vue3 单文件组件（<script setup>）。
// 2) 开发服务器端口固定 5173（与后端 CORS 白名单、SPEC §0 约定一致）。
// 3) 离线展示模式使用 src/api/index.js 内置 Mock 数据，不依赖后端服务。
// 4) 配置 @ 别名指向 src 目录，便于在组件中使用 '@/api'、'@/utils' 等绝对导入。

import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      // @ → 项目 src 目录
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    port: 5173,
    // 开发期允许局域网访问（演示方便）；不影响生产构建
    host: true
  }
})
