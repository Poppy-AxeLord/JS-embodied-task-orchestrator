<script setup>
// 应用根组件 —— 整体布局（SPEC §12）
// 结构：el-container
//   ├─ el-aside（240px 深色侧边栏，el-menu 五个菜单项带 icon）
//   └─ el-container
//        ├─ el-header（应用标题 + 副标题 + 右侧 Mock/已接入 徽标）
//        └─ el-main（<router-view/> 主内容区，带路由切换淡入动画）
// 顶部徽标通过 getHealth() 实时获取后端运行模式。

import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import {
  Grid, // 任务编排
  VideoPlay, // 执行模拟
  DataAnalysis, // 数据看板
  Clock, // 任务历史
  Setting, // 系统设置
  Cpu, // logo 图标
  Connection, // 已接入状态图标
  MagicStick, // Mock 状态图标
  Menu as MenuIcon
} from '@element-plus/icons-vue'
import { getHealth } from '@/api'

const route = useRoute()

// 当前激活的菜单项：跟随路由 path，保证刷新后高亮正确
const activeMenu = computed(() => route.path)

// ---------- 侧边栏菜单配置 ----------
// 每项含：路由路径、中文标题、图标组件、emoji（与 SPEC §12 一致，作为辅助视觉）
const menus = [
  { path: '/task', title: '任务编排', icon: Grid, emoji: '🧩' },
  { path: '/execution', title: '执行模拟', icon: VideoPlay, emoji: '▶️' },
  { path: '/dashboard', title: '数据看板', icon: DataAnalysis, emoji: '📊' },
  { path: '/history', title: '任务历史', icon: Clock, emoji: '🕘' },
  { path: '/settings', title: '系统设置', icon: Setting, emoji: '⚙️' }
]

// ---------- 后端健康状态（Mock / 已接入 徽标） ----------
const health = ref(null) // { status, mock_mode, llm_provider }
const healthLoading = ref(true)
const mobileNavOpen = ref(false)

// 是否 Mock 模式（未配置真实 API Key）
const isMock = computed(() => health.value?.mock_mode !== false)
// 当前 LLM 提供方（用于「已接入 {provider}」文案）
const provider = computed(() => health.value?.llm_provider || '未知')

// 拉取健康状态；失败时静默降级（拦截器已弹错），保持页面可用
async function loadHealth() {
  healthLoading.value = true
  try {
    health.value = await getHealth()
  } catch {
    health.value = null
  } finally {
    healthLoading.value = false
  }
}

onMounted(loadHealth)
</script>

<template>
  <el-container class="app-root">
    <!-- ============ 左侧深色侧边栏 ============ -->
    <el-aside width="240px" class="app-aside desktop-aside">
      <!-- Logo 区 -->
      <div class="logo">
        <el-icon class="logo-icon"><Cpu /></el-icon>
        <div class="logo-text">
          <div class="logo-title">具身智能</div>
          <div class="logo-sub">任务编排平台</div>
        </div>
      </div>

      <!-- 主菜单：深色风格，跟随路由高亮，点击通过 router 跳转 -->
      <el-menu
        :default-active="activeMenu"
        class="app-menu"
        background-color="transparent"
        text-color="#cbd5e1"
        active-text-color="#ffffff"
        router
      >
        <el-menu-item
          v-for="item in menus"
          :key="item.path"
          :index="item.path"
        >
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.title }}</span>
        </el-menu-item>
      </el-menu>

      <!-- 侧边栏底部版本信息 -->
      <div class="aside-footer">
        <span>v1.0 · 数据闭环平台</span>
      </div>
    </el-aside>

    <!-- 手机端改为抽屉导航：不能让固定 240px 侧栏挤压 390px 视口。 -->
    <el-drawer v-model="mobileNavOpen" direction="ltr" size="280px" :with-header="false" class="mobile-nav-drawer">
      <div class="mobile-drawer-content">
        <div class="logo">
          <el-icon class="logo-icon"><Cpu /></el-icon>
          <div class="logo-text"><div class="logo-title">具身智能</div><div class="logo-sub">任务编排平台</div></div>
        </div>
        <el-menu :default-active="activeMenu" class="app-menu" background-color="transparent" text-color="#cbd5e1" active-text-color="#ffffff" router @select="mobileNavOpen = false">
          <el-menu-item v-for="item in menus" :key="item.path" :index="item.path"><el-icon><component :is="item.icon" /></el-icon><span>{{ item.title }}</span></el-menu-item>
        </el-menu>
        <div class="aside-footer"><span>v1.0 · 数据闭环平台</span></div>
      </div>
    </el-drawer>

    <!-- ============ 右侧主体（顶栏 + 内容区） ============ -->
    <el-container class="app-body">
      <!-- 顶部 Header -->
      <el-header class="app-header">
        <div class="header-left">
          <el-button class="mobile-nav-trigger" text circle aria-label="打开导航" @click="mobileNavOpen = true"><el-icon><MenuIcon /></el-icon></el-button>
          <h1 class="header-title">具身智能任务编排平台</h1>
          <span class="header-subtitle">自然语言驱动 · 任务拆解 · 执行仿真 · 数据闭环</span>
        </div>

        <div class="header-right">
          <!-- 运行模式徽标：Mock 模式 / 已接入 {provider} -->
          <el-tag
            v-if="!healthLoading"
            :type="isMock ? 'warning' : 'success'"
            effect="light"
            round
            class="mode-tag"
          >
            <el-icon class="mode-tag-icon">
              <MagicStick v-if="isMock" />
              <Connection v-else />
            </el-icon>
            {{ isMock ? '本地智能引擎' : `已接入 ${provider}` }}
          </el-tag>
          <el-tag v-else type="info" effect="plain" round class="mode-tag">
            连接中…
          </el-tag>
        </div>
      </el-header>

      <!-- 主内容区：路由出口 + 淡入过渡动画 -->
      <el-main class="app-main">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
/* 根容器铺满视口 */
.app-root {
  height: 100vh;
  overflow: hidden;
}

/* ---------- 深色侧边栏 ---------- */
.app-aside {
  background: var(--sidebar-bg);
  display: flex;
  flex-direction: column;
  border-right: 1px solid rgba(255, 255, 255, 0.04);
  position: relative;
  overflow: hidden;
}
.app-aside::after { content: ''; position: absolute; inset: auto -68px -42px auto; width: 250px; height: 250px; background: url('/visuals/orchestration-hero.png') center / cover no-repeat; opacity: .16; border-radius: 50%; filter: saturate(.8) contrast(1.15); pointer-events: none; }
.logo, .app-menu, .aside-footer { position: relative; z-index: 1; }

/* Logo 区 */
.logo {
  height: var(--header-height);
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 20px;
  background: var(--sidebar-bg-deep);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  flex-shrink: 0;
}
.logo-icon {
  font-size: 26px;
  color: var(--brand-light);
}
.logo-text {
  line-height: 1.2;
}
.logo-title {
  font-size: 17px;
  font-weight: 700;
  color: #fff;
  letter-spacing: 1px;
}
.logo-sub {
  font-size: 12px;
  color: #94a3b8;
  letter-spacing: 1px;
}

/* 菜单 */
.app-menu {
  border-right: none;
  flex: 1;
  padding: 12px 12px 0;
}
/* 菜单项圆角 + 间距，贴合现代中后台风格 */
.app-menu :deep(.el-menu-item) {
  position: relative;
  height: 46px;
  line-height: 46px;
  margin-bottom: 6px;
  border-radius: 8px;
  font-size: 14px;
  transition: background-color 0.2s ease, color 0.2s ease;
}
.app-menu :deep(.el-menu-item:hover) {
  background-color: rgba(255, 255, 255, 0.06) !important;
  color: #fff !important;
}
/* 选中项：浅色高亮 + 左侧 3px 主色指示条（Linear/Notion 式） */
.app-menu :deep(.el-menu-item.is-active) {
  background-color: var(--sidebar-active-bg) !important;
  color: var(--sidebar-active-text) !important;
}
.app-menu :deep(.el-menu-item.is-active)::before {
  content: '';
  position: absolute;
  left: 0;
  top: 12px;
  bottom: 12px;
  width: 3px;
  border-radius: 2px;
  background: var(--brand);
}

/* 侧边栏底部 */
.aside-footer {
  flex-shrink: 0;
  padding: 14px 20px;
  font-size: 12px;
  color: #64748b;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}

/* ---------- 右侧主体 ---------- */
.app-body {
  background: var(--bg-page);
  overflow: hidden;
  min-width: 0;
}

/* 顶栏 */
.app-header {
  height: var(--header-height);
  background: #fff;
  border-bottom: 1px solid var(--border-color);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.03);
  flex-shrink: 0;
}
.header-left {
  display: flex;
  align-items: baseline;
  gap: 14px;
}
.header-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}
.header-subtitle {
  font-size: 13px;
  color: var(--text-secondary);
}
.header-right {
  display: flex;
  align-items: center;
}
.mode-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-weight: 500;
  padding: 0 12px;
  height: 30px;
}
.mode-tag-icon {
  margin-right: 2px;
}

/* 主内容区：可滚动，承载各页面；统一 20px 留白避免内容贴边 */
.app-main {
  padding: 20px;
  overflow-y: auto;
  height: calc(100vh - var(--header-height));
  min-width: 0;
}
.mobile-nav-trigger { display: none; font-size: 21px; color: var(--text-primary); }
.mobile-drawer-content { height: 100%; display: flex; flex-direction: column; background: var(--sidebar-bg); margin: -20px; }
.mobile-drawer-content .app-menu { flex: 1; }
.mobile-drawer-content .aside-footer { padding-bottom: 20px; }

/* 窄屏自适应：隐藏副标题，避免顶栏拥挤 */
@media (max-width: 900px) {
  .header-subtitle {
    display: none;
  }
}

@media (max-width: 700px) {
  .desktop-aside { display: none; }
  .mobile-nav-trigger { display: inline-flex; margin-left: -8px; }
  .app-header { padding: 0 12px; }
  .header-left { min-width: 0; gap: 6px; }
  .header-title { font-size: 16px; line-height: 1.25; }
  .header-right { display: none; }
  .app-main { padding: 12px; height: calc(100vh - var(--header-height)); }
  .app-main :deep(.el-col) { flex: 0 0 100%; max-width: 100%; }
}

:global(.mobile-nav-drawer .el-drawer) { background: var(--sidebar-bg); }
:global(.mobile-nav-drawer .el-drawer__body) { padding: 20px; overflow: hidden; }
</style>
