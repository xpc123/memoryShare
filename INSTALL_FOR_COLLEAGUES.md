# 给同事的安装说明

## 快速安装（3 步）

### 1. 安装包

根据我提供的方式选择：

**方式 A：从文件安装（如果你收到了 .whl 文件）**
```bash
pip install memory-share-0.1.0-py3-none-any.whl
```

**方式 B：从 PyPI 安装（如果已发布）**
```bash
pip install memory-share
```

**方式 C：从 Git 安装**
```bash
pip install git+https://github.com/xpc123/memoryShare.git
```

### 2. 在项目中初始化

```bash
cd /path/to/your/project
memory-share init
```

### 3. 重启 IDE

重启你的 Cursor/Claude Code/Copilot，让配置生效。

## 开始使用

### 自动功能

- ✅ 每次新会话自动加载之前的记忆
- ✅ Git 提交自动记录到记忆

### 手动同步

在 AI 会话中说：
- "sync memory" / "同步记忆" / "保存进度"

AI 会智能同步记忆。

### 查看记忆

```bash
memory-share status    # 查看状态
memory-share log       # 查看日志
memory-share search <关键词>  # 搜索
```

## 详细文档

完整使用指南请查看：[USER_GUIDE.md](USER_GUIDE.md)

## 遇到问题？

1. 运行 `memory-share doctor` 检查
2. 查看 `memory-share status` 状态
3. 参考 [USER_GUIDE.md](USER_GUIDE.md) 的常见问题部分
