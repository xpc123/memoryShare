# Memory Share 用户使用指南

本文档说明如何安装和使用 Memory Share 来在多个 AI IDE 之间共享记忆。

## 📦 安装

根据你收到的方式，选择对应的安装方法：

### 方式 1：从 PyPI 安装（如果已发布）

```bash
pip install memory-share
```

### 方式 2：从本地文件安装（推荐）

如果你收到了 `.whl` 或 `.tar.gz` 文件：

```bash
# 从 wheel 文件安装（推荐，更快）
pip install memory-share-0.1.0-py3-none-any.whl

# 或从源码包安装
pip install memory-share-0.1.0.tar.gz
```

### 方式 3：从 Git 仓库安装

```bash
# 从 GitHub 安装
pip install git+https://github.com/xpc123/memoryShare.git

# 或从特定版本安装
pip install git+https://github.com/xpc123/memoryShare.git@v0.1.0
```

### 方式 4：从源码安装（开发模式）

```bash
# 克隆仓库
git clone https://github.com/xpc123/memoryShare.git
cd memoryShare

# 创建虚拟环境（推荐）
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# 或 .venv\Scripts\activate  # Windows

# 安装
pip install -e .
```

### 验证安装

安装完成后，验证是否成功：

```bash
memory-share --help
```

如果看到帮助信息，说明安装成功！

## 🚀 快速开始

### 步骤 1：在项目中初始化

进入你的项目目录，运行初始化命令：

```bash
cd /path/to/your/project
memory-share init
```

这个命令会：
- ✅ 创建 `.memory/` 目录（用于存储记忆）
- ✅ 扫描项目（读取 README、Git 历史、技术栈）
- ✅ 自动配置所有 IDE 的 MCP 设置：
  - Cursor: `.cursor/mcp.json`
  - Claude Code: `.mcp.json`
  - GitHub Copilot: `.vscode/mcp.json`
- ✅ 安装 IDE 规则文件（告诉 AI 如何使用 Memory Share）
- ✅ 安装 Git 钩子（自动记录提交信息）

**重要**：`.memory/` 目录会被添加到 `.gitignore`，不会提交到 Git。每个开发者需要在自己的机器上运行 `init`。

### 步骤 2：重启 IDE

初始化完成后，**重启你的 IDE**（Cursor/Claude Code/Copilot），让 MCP 配置生效。

### 步骤 3：开始使用

现在你可以在 IDE 中正常使用 AI 了！Memory Share 会自动工作：

#### 自动加载记忆

每次打开新的 AI 会话时，AI 会自动读取 `memory://briefing` 资源，加载之前所有会话的上下文。

#### 手动同步记忆

在会话中，你可以随时说：
- "sync memory" / "同步记忆" / "更新记忆" / "保存进度"

AI 会执行智能同步：
1. **拉取**：从其他 IDE 会话获取新的事件
2. **评估**：判断当前会话是否包含项目相关信息
3. **推送**：如果相关，生成摘要并保存；如果不相关，跳过保存

#### 查看记忆状态

使用命令行工具查看：

```bash
# 查看记忆健康状态
memory-share status

# 查看最近的记忆事件
memory-share log

# 搜索记忆
memory-share search <关键词>

# 查看所有任务
memory-share tasks

# 查看项目上下文
memory-share context
```

## 💡 使用场景

### 场景 1：在 Cursor 中开始工作，切换到 Claude Code 继续

1. 在 Cursor 中：
   - 开始一个新功能
   - 说 "sync memory" 保存进度
   - AI 会生成摘要并保存

2. 切换到 Claude Code：
   - 打开同一个项目
   - 开始新的会话
   - AI 自动加载之前的上下文
   - 继续之前的工作

### 场景 2：团队协作

多个开发者使用同一个项目：

1. 开发者 A 在 Cursor 中修复了一个 bug
2. 开发者 A 说 "sync memory" 保存
3. 开发者 B 在 Claude Code 中开始新会话
4. AI 自动告诉开发者 B："之前有人修复了 XXX bug"

### 场景 3：跨会话记忆

即使在同一 IDE 中：

1. 会话 1：你完成了功能 A
2. 说 "sync memory" 保存
3. 关闭会话 1，开始会话 2
4. 会话 2 的 AI 知道功能 A 已经完成

## 🔧 配置说明

### MCP 配置文件

`memory-share init` 会自动创建以下配置文件：

- **Cursor**: `.cursor/mcp.json`
- **Claude Code**: `.mcp.json`
- **GitHub Copilot**: `.vscode/mcp.json`

这些文件已经配置好了，通常不需要手动修改。

### 项目配置

`.memory/config.json` 包含可调整的参数：

```json
{
  "briefing_token_budget": 3000,    // 摘要的最大 token 数
  "hot_memory_hours": 48,            // 热记忆保留时间（小时）
  "warm_memory_days": 30,            // 温记忆保留时间（天）
  "session_ttl_days": 7,             // 会话过期时间（天）
  "max_sessions_per_ide": 3          // 每个 IDE 保留的最大会话数
}
```

如需修改，直接编辑这个文件。

## 📋 常用命令

```bash
# 初始化项目
memory-share init

# 查看状态
memory-share status

# 查看日志
memory-share log [--limit N]

# 搜索记忆
memory-share search <关键词>

# 查看任务
memory-share tasks

# 查看上下文
memory-share context

# 手动同步
memory-share sync [--pull] [--push] [--summary "..."]

# 压缩旧记忆
memory-share compact

# 健康检查
memory-share doctor
```

## ❓ 常见问题

### Q1: 安装后找不到 `memory-share` 命令？

**A**: 确保 Python 的 `bin` 目录在 PATH 中：
```bash
# 检查安装位置
pip show memory-share

# 如果使用虚拟环境，确保已激活
source .venv/bin/activate
```

### Q2: IDE 中 AI 没有自动加载记忆？

**A**: 检查以下几点：
1. 是否运行了 `memory-share init`？
2. 是否重启了 IDE？
3. 检查 MCP 配置是否正确（`.cursor/mcp.json` 等）
4. 查看 IDE 的 MCP 日志是否有错误

### Q3: 如何确认 MCP 服务器正在运行？

**A**: 在 IDE 中，AI 应该能够访问 `memory://briefing` 资源。你也可以：
```bash
# 检查状态
memory-share status

# 查看是否有错误
memory-share doctor
```

### Q4: 多个开发者如何使用？

**A**: 
- 每个开发者在自己的机器上运行 `memory-share init`
- `.memory/` 目录是本地存储，不会同步到 Git
- 如果需要共享记忆，可以考虑：
  - 将 `.memory/` 目录放在共享网络位置
  - 或使用 Git 手动同步 `.memory/`（需要解决冲突）

### Q5: 如何清除所有记忆？

**A**: 
```bash
# 删除 .memory 目录
rm -rf .memory/

# 重新初始化
memory-share init
```

### Q6: 记忆文件太大怎么办？

**A**: 
```bash
# 压缩旧记忆
memory-share compact

# 这会：
# - 将旧事件压缩成摘要
# - 归档到 archive/ 目录
# - 清理过期会话
```

### Q7: 如何备份记忆？

**A**: 
```bash
# 备份整个 .memory 目录
cp -r .memory .memory.backup

# 或使用 Git（如果 .memory 不在 .gitignore 中）
git add .memory/
git commit -m "Backup memory"
```

### Q8: 支持哪些 IDE？

**A**: 目前支持：
- ✅ Cursor
- ✅ Claude Code
- ✅ GitHub Copilot (VS Code)

其他支持 MCP 的 IDE 理论上也可以使用，但需要手动配置。

## 🆘 获取帮助

如果遇到问题：

1. 查看日志：`memory-share log`
2. 运行诊断：`memory-share doctor`
3. 检查状态：`memory-share status`
4. 查看项目 README 和 `PUBLISHING.md`

## 📝 最佳实践

1. **定期同步**：完成重要里程碑后说 "sync memory"
2. **使用描述性摘要**：AI 生成的摘要应该清晰描述做了什么
3. **过滤无关内容**：AI 会自动过滤个人问题等无关内容
4. **定期压缩**：如果项目很大，定期运行 `memory-share compact`
5. **查看状态**：定期运行 `memory-share status` 检查健康状态

---

**祝你使用愉快！** 🎉
