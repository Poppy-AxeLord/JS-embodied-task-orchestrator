// 前端应用入口
// 职责：
// 1) 创建 Vue 应用实例。
// 2) 注册全局插件：vue-router（路由）、Element Plus（UI 组件库）。
// 3) 全量注册 @element-plus/icons-vue 图标为全局组件，便于在任意页面使用 <el-icon><XXX/></el-icon>。
// 4) 引入 Element Plus 样式与项目全局样式 global.css。

import { createApp } from 'vue'
import App from './App.vue'

// 路由表（见 src/router/index.js）
import router from './router'

// Element Plus 组件库及其默认样式
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
// Element Plus 中文语言包：让分页、日期选择器等内置文案显示为中文
import zhCn from 'element-plus/es/locale/lang/zh-cn'

// Element Plus 全套图标
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

// 项目全局样式（背景色、卡片、滚动条美化、工具类等）
import './styles/global.css'

// 创建应用实例
const app = createApp(App)

// 全量注册图标组件：以图标英文名作为组件名注册为全局组件
for (const [name, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(name, component)
}

// 安装插件：路由 + Element Plus（指定中文语言包）
app.use(router)
app.use(ElementPlus, { locale: zhCn })

// 挂载到 index.html 中的 #app 节点
app.mount('#app')
