// 前端路由表（SPEC §12）
// 使用 HTML5 History 模式（createWebHistory），URL 干净无 # 号。
// 路由与页面对应关系：
//   /          → 重定向到 /dashboard（落地即见数据看板，开场有数据感冲击）
//   /task      → 任务编排（TaskEditor）
//   /execution → 执行模拟（Execution）
//   /dashboard → 数据看板（Dashboard）
//   /history   → 任务历史（History）
//   /settings  → 系统设置（Settings）

import { createRouter, createWebHistory } from 'vue-router'

// 路由懒加载：按需分包，首屏更快
const routes = [
  {
    // 落地页优先展示数据看板：打开即见 150+ 样本聚合的指标与图表，
    // 演示时「开场即有数据感冲击」，再顺流进入任务编排 → 执行 → 闭环。
    path: '/',
    redirect: '/dashboard'
  },
  {
    path: '/task',
    name: 'task',
    component: () => import('@/views/TaskEditor.vue'),
    meta: { title: '任务编排' }
  },
  {
    path: '/execution',
    name: 'execution',
    component: () => import('@/views/Execution.vue'),
    meta: { title: '执行模拟' }
  },
  {
    path: '/dashboard',
    name: 'dashboard',
    component: () => import('@/views/Dashboard.vue'),
    meta: { title: '数据看板' }
  },
  {
    path: '/history',
    name: 'history',
    component: () => import('@/views/History.vue'),
    meta: { title: '任务历史' }
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('@/views/Settings.vue'),
    meta: { title: '系统设置' }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  // 切换路由时滚动回顶部，符合中后台习惯
  scrollBehavior() {
    return { top: 0 }
  }
})

// 全局后置守卫：根据路由 meta.title 动态设置浏览器标题
router.afterEach((to) => {
  const base = '具身智能任务编排平台'
  document.title = to.meta?.title ? `${to.meta.title} · ${base}` : base
})

export default router
