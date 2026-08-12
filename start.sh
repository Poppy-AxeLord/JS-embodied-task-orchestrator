#!/bin/bash
# =============================================================================
# start.sh —— 一键启动脚本（具身智能任务编排平台）
# -----------------------------------------------------------------------------
# 作用：
#   1) 激活 backend/.venv 虚拟环境
#   2) 后台启动后端：在 backend 目录执行 uvicorn main:app --reload --port 8000，记录 PID
#   3) 前台启动前端：在 frontend 目录执行 npm run dev
#   4) 通过 trap 捕获 Ctrl+C(INT) / 退出(EXIT)，自动 kill 后端进程，避免端口残留
# 说明：本脚本默认在“项目根目录”执行（路径可能含空格与中文，已全部用引号包裹）
#   · 后端端口：8000   前端开发服务器端口：5173
# =============================================================================

# 任一命令出错即退出
set -e

# -----------------------------------------------------------------------------
# 终端彩色输出辅助（纯 ANSI，无第三方依赖）
# -----------------------------------------------------------------------------
COLOR_RESET='\033[0m'
COLOR_BLUE='\033[1;34m'
COLOR_GREEN='\033[1;32m'
COLOR_YELLOW='\033[1;33m'
COLOR_RED='\033[1;31m'

print_step() {
  echo ""
  echo -e "${COLOR_BLUE}========================================================${COLOR_RESET}"
  echo -e "${COLOR_BLUE}  $1${COLOR_RESET}"
  echo -e "${COLOR_BLUE}========================================================${COLOR_RESET}"
}
print_ok()   { echo -e "${COLOR_GREEN}[成功] $1${COLOR_RESET}"; }
print_warn() { echo -e "${COLOR_YELLOW}[提示] $1${COLOR_RESET}"; }
print_err()  { echo -e "${COLOR_RED}[错误] $1${COLOR_RESET}"; }

# -----------------------------------------------------------------------------
# 定位项目根目录（以脚本所在目录为准，兼容含空格/中文的路径）
# -----------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

# 用于记录后端进程 PID，trap 清理时使用
BACKEND_PID=""

echo ""
echo -e "${COLOR_BLUE}#############################################################${COLOR_RESET}"
echo -e "${COLOR_BLUE}#   具身智能任务编排平台 · 一键启动（start.sh）            #${COLOR_RESET}"
echo -e "${COLOR_BLUE}#############################################################${COLOR_RESET}"
echo -e "项目根目录：${ROOT_DIR}"

# -----------------------------------------------------------------------------
# 清理函数：捕获中断/退出信号时调用，确保后台后端进程被正确结束
#   —— 同时清理可能存在的子进程（uvicorn --reload 会派生 reloader 子进程）
# -----------------------------------------------------------------------------
cleanup() {
  echo ""
  print_warn "正在停止服务，清理后端进程……"
  if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
    # 先尝试结束整个进程组（负号表示进程组），失败再退回结束单个 PID
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
    # 给后端一点时间优雅退出
    sleep 1
    # 若仍存活则强制结束
    if kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
      kill -9 "$BACKEND_PID" >/dev/null 2>&1 || true
    fi
    print_ok "后端进程（PID=$BACKEND_PID）已停止。"
  fi
  # 清空 PID，避免 EXIT 与 INT 双重触发时重复处理
  BACKEND_PID=""
}

# 捕获 Ctrl+C(INT) 与 脚本退出(EXIT)，统一执行清理
# 注意：前端在前台运行，用户 Ctrl+C 时会先触发 INT，再触发 EXIT，cleanup 做了幂等处理
trap cleanup INT EXIT

# =============================================================================
# 第 1 步：基础检查（虚拟环境与依赖是否就绪）
# =============================================================================
print_step "第 1/3 步：环境检查"

VENV_DIR="$BACKEND_DIR/.venv"
VENV_ACTIVATE="$VENV_DIR/bin/activate"

if [ ! -f "$VENV_ACTIVATE" ]; then
  print_err "未找到后端虚拟环境：$VENV_DIR"
  echo "      请先在项目根目录运行 ./setup.sh 完成环境初始化。"
  exit 1
fi

if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  print_err "未找到前端依赖（frontend/node_modules）。"
  echo "      请先在项目根目录运行 ./setup.sh 完成依赖安装。"
  exit 1
fi

print_ok "虚拟环境与前端依赖均已就绪。"

# =============================================================================
# 第 2 步：后台启动后端（uvicorn，端口 8000），并记录 PID
#   —— 在子 shell 中切换到 backend 目录后启动，保证 main:app 的导入路径正确
#   —— 使用 & 放入后台，$! 取得其 PID
# =============================================================================
print_step "第 2/3 步：启动后端服务（FastAPI / uvicorn，端口 8000）"

# 激活虚拟环境（当前 shell 内激活，便于后续使用 uvicorn）
# shellcheck disable=SC1090
source "$VENV_ACTIVATE"
print_ok "已激活虚拟环境：$VENV_DIR"

echo "正在后台启动后端（uvicorn main:app --reload --port 8000）……"
# 在子 shell 中进入 backend 目录再启动，避免改变主脚本工作目录；
# 优先用 python -m uvicorn，确保使用 venv 内的 uvicorn。
(
  cd "$BACKEND_DIR"
  exec python -m uvicorn main:app --reload --port 8000
) &
BACKEND_PID=$!

print_ok "后端已在后台启动，进程 PID=${BACKEND_PID}。"
print_warn "后端地址： http://localhost:8000   （接口文档： http://localhost:8000/docs）"

# 等待数秒，给后端留出建表 / 初始化演示数据的时间，并确认进程没有立即崩溃
sleep 3
if ! kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
  print_err "后端进程启动失败或已退出，请检查上方日志（常见原因：依赖缺失 / 端口 8000 被占用）。"
  exit 1
fi
print_ok "后端进程运行中。"

# =============================================================================
# 第 3 步：前台启动前端（Vite 开发服务器，端口 5173）
#   —— 前台运行，便于直接看到前端日志；用户 Ctrl+C 退出时由 trap 统一清理后端
# =============================================================================
print_step "第 3/3 步：启动前端开发服务器（Vite / Vue3，端口 5173）"

echo ""
echo -e "${COLOR_GREEN}#############################################################${COLOR_RESET}"
echo -e "${COLOR_GREEN}#   前后端服务即将就绪！                                   #${COLOR_RESET}"
echo -e "${COLOR_GREEN}#   请在浏览器访问： http://localhost:5173                 #${COLOR_RESET}"
echo -e "${COLOR_GREEN}#   按 Ctrl+C 可同时停止前端与后端服务                     #${COLOR_RESET}"
echo -e "${COLOR_GREEN}#############################################################${COLOR_RESET}"
echo ""

# 在子 shell 中进入 frontend 目录前台运行 npm run dev；
# 该命令会持续占用前台，直到用户 Ctrl+C，届时触发 trap cleanup。
(
  cd "$FRONTEND_DIR"
  npm run dev
)

# 正常情况下脚本会阻塞在上面的 npm run dev；
# 当其退出（用户结束）后，EXIT trap 会触发 cleanup 收尾。
