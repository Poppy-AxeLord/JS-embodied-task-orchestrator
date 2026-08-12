#!/bin/bash
# =============================================================================
# setup.sh —— 一键环境初始化脚本（具身智能任务编排平台）
# -----------------------------------------------------------------------------
# 适用平台：macOS（Apple Silicon / Intel 均可）
# 作用：
#   1) 检测 Homebrew / Node.js / Python3 是否安装，未安装则给出安装提示（不强制静默安装）
#   2) 用 python3 -m venv 在 backend/.venv 创建虚拟环境，并 pip 安装后端依赖
#   3) 进入 frontend 执行 npm install 安装前端依赖
#   4) 若不存在 backend/.env 则复制 backend/.env.example -> backend/.env
#   5) 每一步均有清晰中文进度提示与失败检查
# 说明：本脚本默认在“项目根目录”执行（路径可能含空格与中文，已全部用引号包裹）
# =============================================================================

# 任一命令出错即退出，避免在错误状态下继续执行
set -e

# -----------------------------------------------------------------------------
# 终端彩色输出辅助（不依赖第三方工具，纯 ANSI 转义）
# -----------------------------------------------------------------------------
COLOR_RESET='\033[0m'
COLOR_BLUE='\033[1;34m'    # 步骤标题：B 端专业蓝
COLOR_GREEN='\033[1;32m'   # 成功
COLOR_YELLOW='\033[1;33m'  # 警告 / 需手动处理
COLOR_RED='\033[1;31m'     # 错误

# 打印一个带分隔线的步骤标题
print_step() {
  echo ""
  echo -e "${COLOR_BLUE}========================================================${COLOR_RESET}"
  echo -e "${COLOR_BLUE}  $1${COLOR_RESET}"
  echo -e "${COLOR_BLUE}========================================================${COLOR_RESET}"
}

# 打印成功 / 警告 / 错误信息
print_ok()   { echo -e "${COLOR_GREEN}[成功] $1${COLOR_RESET}"; }
print_warn() { echo -e "${COLOR_YELLOW}[提示] $1${COLOR_RESET}"; }
print_err()  { echo -e "${COLOR_RED}[错误] $1${COLOR_RESET}"; }

# -----------------------------------------------------------------------------
# 定位项目根目录：以脚本所在目录为准，避免“当前工作目录”不确定带来的路径问题
# 注意：${BASH_SOURCE[0]} 可能含空格/中文，必须用引号
# -----------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

echo ""
echo -e "${COLOR_BLUE}#############################################################${COLOR_RESET}"
echo -e "${COLOR_BLUE}#   具身智能任务编排平台 · 环境初始化（setup.sh）           #${COLOR_RESET}"
echo -e "${COLOR_BLUE}#############################################################${COLOR_RESET}"
echo -e "项目根目录：${ROOT_DIR}"

# =============================================================================
# 第 1 步：检测基础环境（Homebrew / Node / Python3）
#   —— 仅检测并给出安装建议，不执行任何危险的静默安装操作
# =============================================================================
print_step "第 1/5 步：检测基础开发环境"

# ---- 1.1 Homebrew（macOS 包管理器，用于安装 Node / Python 等）----
if command -v brew >/dev/null 2>&1; then
  print_ok "已检测到 Homebrew：$(brew --version | head -n 1)"
else
  print_warn "未检测到 Homebrew（macOS 推荐用它来安装 Node / Python）。"
  echo "      可在终端执行官方安装命令（请自行确认后再运行）："
  echo '      /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
  echo "      安装完成后，按提示把 brew 加入 PATH，再重新运行本脚本。"
fi

# ---- 1.2 Node.js（前端 Vite/Vue 运行所需，要求 18+）----
if command -v node >/dev/null 2>&1; then
  NODE_VER="$(node --version)"
  print_ok "已检测到 Node.js：${NODE_VER}"
  # 简单校验主版本号是否 >= 18（去掉前缀 v 再取第一段）
  NODE_MAJOR="$(echo "${NODE_VER#v}" | cut -d. -f1)"
  if [ "${NODE_MAJOR:-0}" -lt 18 ]; then
    print_warn "Node 版本偏低（建议 18 及以上），当前为 ${NODE_VER}，可能影响 Vite 5 运行。"
    echo "      升级建议：brew install node  或  brew upgrade node"
  fi
else
  print_err "未检测到 Node.js（前端必需，要求 18+）。"
  echo "      安装建议（任选其一）："
  echo "        · 使用 Homebrew： brew install node"
  echo "        · 或前往官网下载 LTS 版本： https://nodejs.org/"
  echo "      安装完成后重新运行本脚本。"
  exit 1
fi

# ---- 1.3 npm（随 Node 附带）----
if command -v npm >/dev/null 2>&1; then
  print_ok "已检测到 npm：v$(npm --version)"
else
  print_err "未检测到 npm（通常随 Node.js 一起安装），请检查 Node 安装是否完整。"
  exit 1
fi

# ---- 1.4 Python3（后端 FastAPI 运行所需，要求 3.10+）----
if command -v python3 >/dev/null 2>&1; then
  PY_VER="$(python3 --version 2>&1)"
  print_ok "已检测到 Python3：${PY_VER}"
else
  print_err "未检测到 Python3（后端必需，要求 3.10+）。"
  echo "      安装建议（任选其一）："
  echo "        · 使用 Homebrew： brew install python"
  echo "        · 或前往官网下载： https://www.python.org/downloads/macos/"
  echo "      安装完成后重新运行本脚本。"
  exit 1
fi

# =============================================================================
# 第 2 步：创建后端 Python 虚拟环境（backend/.venv）
#   —— 优先使用 python3 -m venv，纯标准库方案，无需 conda，Apple Silicon 友好
# =============================================================================
print_step "第 2/5 步：创建后端虚拟环境 backend/.venv"

if [ ! -d "$BACKEND_DIR" ]; then
  print_err "未找到 backend 目录：$BACKEND_DIR"
  echo "      请确认在“项目根目录”下运行本脚本。"
  exit 1
fi

if [ -d "$BACKEND_DIR/.venv" ]; then
  print_ok "虚拟环境已存在（backend/.venv），跳过创建。"
else
  echo "正在创建虚拟环境（python3 -m venv backend/.venv）……"
  python3 -m venv "$BACKEND_DIR/.venv"
  print_ok "虚拟环境创建完成：$BACKEND_DIR/.venv"
fi

# =============================================================================
# 第 3 步：在虚拟环境中安装后端依赖（backend/requirements.txt）
#   —— 直接调用 venv 内的 pip，避免“是否已激活”的歧义；依赖全部为纯 Python，无需编译
# =============================================================================
print_step "第 3/5 步：安装后端依赖（pip install -r backend/requirements.txt）"

VENV_PY="$BACKEND_DIR/.venv/bin/python"
REQ_FILE="$BACKEND_DIR/requirements.txt"

if [ ! -f "$REQ_FILE" ]; then
  print_err "未找到依赖清单：$REQ_FILE"
  exit 1
fi

echo "正在升级 pip（确保使用较新解析器，安装更顺畅）……"
"$VENV_PY" -m pip install --upgrade pip

echo "正在安装后端依赖（首次安装可能需要 1~3 分钟，请耐心等待）……"
"$VENV_PY" -m pip install -r "$REQ_FILE"
print_ok "后端依赖安装完成。"

# =============================================================================
# 第 4 步：安装前端依赖（cd frontend && npm install）
# =============================================================================
print_step "第 4/5 步：安装前端依赖（npm install）"

if [ ! -d "$FRONTEND_DIR" ]; then
  print_err "未找到 frontend 目录：$FRONTEND_DIR"
  exit 1
fi

if [ ! -f "$FRONTEND_DIR/package.json" ]; then
  print_err "未找到前端 package.json：$FRONTEND_DIR/package.json"
  exit 1
fi

# 使用子 shell + 引号路径进入前端目录，避免污染当前脚本的工作目录
echo "正在安装前端依赖（首次安装可能需要数分钟，请耐心等待）……"
(
  cd "$FRONTEND_DIR"
  npm install
)
print_ok "前端依赖安装完成。"

# =============================================================================
# 第 5 步：准备后端环境变量文件（.env）
#   —— 若不存在 backend/.env 则从 backend/.env.example 复制；留空即用 Mock 模式
# =============================================================================
print_step "第 5/5 步：准备后端环境变量文件 backend/.env"

ENV_FILE="$BACKEND_DIR/.env"
ENV_EXAMPLE="$BACKEND_DIR/.env.example"

if [ -f "$ENV_FILE" ]; then
  print_ok "backend/.env 已存在，保留现有配置（不覆盖）。"
elif [ -f "$ENV_EXAMPLE" ]; then
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  print_ok "已从 .env.example 复制生成 backend/.env。"
  print_warn "默认未配置任何大模型 API Key，将以【Mock 模式】运行（全功能可演示）。"
  echo "      如需接入真实大模型，请编辑 backend/.env 填入对应的 API Key 与 provider。"
else
  print_warn "未找到 backend/.env.example，跳过 .env 生成。后端将按默认值以 Mock 模式运行。"
fi

# =============================================================================
# 收尾：完成提示
# =============================================================================
echo ""
echo -e "${COLOR_GREEN}#############################################################${COLOR_RESET}"
echo -e "${COLOR_GREEN}#   环境初始化全部完成！                                   #${COLOR_RESET}"
echo -e "${COLOR_GREEN}#############################################################${COLOR_RESET}"
echo ""
echo -e "下一步：在项目根目录执行 ${COLOR_BLUE}./start.sh${COLOR_RESET} 一键启动前后端服务。"
echo -e "（若提示无执行权限，请先运行： ${COLOR_BLUE}chmod +x setup.sh start.sh${COLOR_RESET}）"
echo ""
echo -e "启动后访问： ${COLOR_BLUE}http://localhost:5173${COLOR_RESET}"
echo ""
