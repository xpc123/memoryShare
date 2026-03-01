# 打包和发布指南

本文档说明如何将 Memory Share 打包并发布给其他人使用。

> 📖 **用户使用指南**：发布后，请让用户参考 [USER_GUIDE.md](USER_GUIDE.md) 了解如何安装和使用。

## 方式一：发布到 PyPI（推荐）

### 1. 准备工作

```bash
# 确保在虚拟环境中
source .venv/bin/activate

# 安装构建工具
pip install --upgrade build twine
```

### 2. 更新版本号

在发布新版本前，更新版本号：

- `pyproject.toml` 中的 `version = "0.1.0"`
- `src/memory_share/__init__.py` 中的 `__version__ = "0.1.0"`

### 3. 构建分发包

```bash
# 清理旧的构建文件
rm -rf dist/ build/ *.egg-info

# 构建源码分发包和 wheel
python -m build
```

这会在 `dist/` 目录下生成：
- `memory-share-0.1.0.tar.gz` (源码分发包)
- `memory-share-0.1.0-py3-none-any.whl` (wheel 包)

### 4. 检查分发包

```bash
# 检查分发包内容
twine check dist/*

# 测试安装（可选）
pip install dist/memory-share-0.1.0-py3-none-any.whl
```

### 5. 发布到 PyPI

#### 测试 PyPI（推荐先测试）

```bash
# 上传到测试 PyPI
twine upload --repository testpypi dist/*

# 从测试 PyPI 安装测试
pip install --index-url https://test.pypi.org/simple/ memory-share
```

#### 正式 PyPI

```bash
# 上传到正式 PyPI
twine upload dist/*
```

**注意**：需要 PyPI 账号和 API token。在 https://pypi.org/account/register/ 注册账号，然后在 https://pypi.org/manage/account/token/ 创建 API token。

### 6. 安装使用

发布后，其他人可以通过以下方式安装：

```bash
pip install memory-share
```

## 方式二：本地分发（不发布到 PyPI）

### 1. 构建分发包

```bash
# 在项目根目录
python -m build
```

### 2. 分发文件

将 `dist/` 目录下的文件发送给用户：
- `memory-share-0.1.0.tar.gz`
- `memory-share-0.1.0-py3-none-any.whl`

### 3. 用户安装

用户可以通过以下方式安装：

```bash
# 从 wheel 文件安装（推荐，更快）
pip install memory-share-0.1.0-py3-none-any.whl

# 或从源码分发包安装
pip install memory-share-0.1.0.tar.gz

# 或从本地目录安装
pip install /path/to/memory-share-0.1.0.tar.gz
```

## 方式三：GitHub Releases

### 1. 构建分发包

```bash
python -m build
```

### 2. 创建 Git Tag

```bash
git tag -a v0.1.0 -m "Release version 0.1.0"
git push origin v0.1.0
```

### 3. 创建 GitHub Release

1. 访问 GitHub 仓库的 Releases 页面
2. 点击 "Draft a new release"
3. 选择刚创建的 tag (v0.1.0)
4. 填写 Release 标题和描述
5. 上传 `dist/` 目录下的文件：
   - `memory-share-0.1.0.tar.gz`
   - `memory-share-0.1.0-py3-none-any.whl`
6. 发布

### 4. 用户安装

用户可以从 GitHub Releases 下载并安装：

```bash
# 下载文件后
pip install memory-share-0.1.0-py3-none-any.whl
```

或者直接从 GitHub 安装（如果仓库是公开的）：

```bash
pip install git+https://github.com/xpc123/memoryShare.git@v0.1.0
```

## 方式四：从 Git 仓库直接安装

如果代码在 Git 仓库中，用户可以直接安装：

```bash
# 从 GitHub
pip install git+https://github.com/xpc123/memoryShare.git

# 从特定分支
pip install git+https://github.com/xpc123/memoryShare.git@main

# 从特定 tag
pip install git+https://github.com/xpc123/memoryShare.git@v0.1.0

# 从本地仓库
pip install -e /path/to/memory-share
```

## 验证打包

在发布前，建议验证打包配置：

```bash
# 检查项目配置
python -m build --check

# 检查分发包内容
python -m zipfile -l dist/memory-share-0.1.0-py3-none-any.whl

# 测试安装到临时环境
python -m venv /tmp/test_install
/tmp/test_install/bin/pip install dist/memory-share-0.1.0-py3-none-any.whl
/tmp/test_install/bin/memory-share --help
```

## 版本管理建议

使用语义化版本（Semantic Versioning）：
- **主版本号**：不兼容的 API 修改
- **次版本号**：向下兼容的功能性新增
- **修订号**：向下兼容的问题修正

示例：
- `0.1.0` → `0.1.1` (bug fix)
- `0.1.1` → `0.2.0` (new features)
- `0.2.0` → `1.0.0` (stable release)

## 常见问题

### Q: 打包时提示缺少文件？

A: 检查 `MANIFEST.in` 和 `pyproject.toml` 中的 `package-data` 配置。

### Q: 用户安装后找不到 templates？

A: 确保 `pyproject.toml` 中配置了：
```toml
[tool.setuptools.package-data]
memory_share = ["templates/*"]
```

### Q: 如何更新已发布的版本？

A: 更新版本号后重新构建和发布。PyPI 不允许覆盖已发布的版本。

## 快速发布脚本

创建一个 `publish.sh` 脚本：

```bash
#!/bin/bash
set -e

echo "Cleaning old builds..."
rm -rf dist/ build/ *.egg-info

echo "Building package..."
python -m build

echo "Checking package..."
twine check dist/*

echo "Build complete! Files in dist/:"
ls -lh dist/

echo ""
echo "To publish to PyPI:"
echo "  twine upload dist/*"
echo ""
echo "To publish to Test PyPI:"
echo "  twine upload --repository testpypi dist/*"
```

使用方法：
```bash
chmod +x publish.sh
./publish.sh
```
