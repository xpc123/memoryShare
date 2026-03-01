# 推送到 GitHub 的说明

项目已经初始化并准备好推送，但需要设置 GitHub 身份验证。

## 当前状态

✅ Git 仓库已初始化  
✅ 所有文件已提交（2个提交）  
✅ 远程仓库已配置：`https://github.com/xpc123/memoryShare.git`  
⏳ 等待推送到 GitHub

## 推送方法（选择一种）

### 方法 1：使用 Personal Access Token (PAT) - 推荐

1. **创建 GitHub Personal Access Token**：
   - 访问：https://github.com/settings/tokens
   - 点击 "Generate new token" → "Generate new token (classic)"
   - 设置名称：`memoryShare-push`
   - 选择权限：至少勾选 `repo`（完整仓库权限）
   - 点击 "Generate token"
   - **复制 token**（只显示一次！）

2. **推送代码**：
   ```bash
   cd /vols/cpg_bj_ADE2/users/xpengche/project/memoryShare
   
   # 使用 token 作为密码推送
   git push -u origin main
   # 用户名：xpc123
   # 密码：粘贴你的 token
   ```

   或者使用 token 直接推送：
   ```bash
   git push https://<YOUR_TOKEN>@github.com/xpc123/memoryShare.git main
   ```

### 方法 2：使用 SSH（如果已配置 SSH 密钥）

1. **检查 SSH 密钥**：
   ```bash
   ls -la ~/.ssh/id_*.pub
   ```

2. **如果没有 SSH 密钥，生成一个**：
   ```bash
   ssh-keygen -t ed25519 -C "your_email@example.com"
   # 将公钥添加到 GitHub: https://github.com/settings/keys
   ```

3. **切换到 SSH URL 并推送**：
   ```bash
   cd /vols/cpg_bj_ADE2/users/xpengche/project/memoryShare
   git remote set-url origin git@github.com:xpc123/memoryShare.git
   git push -u origin main
   ```

### 方法 3：使用 GitHub CLI

如果已安装 `gh` 命令行工具：

```bash
cd /vols/cpg_bj_ADE2/users/xpengche/project/memoryShare
gh auth login
git push -u origin main
```

## 推送后

推送成功后，你的同事可以通过以下方式安装：

```bash
pip install git+https://github.com/xpc123/memoryShare.git
```

## 验证推送

推送后，访问 https://github.com/xpc123/memoryShare 确认代码已上传。

## 注意事项

1. **确保 GitHub 仓库已创建**：
   - 如果仓库不存在，先访问 https://github.com/new 创建 `memoryShare` 仓库
   - 不要初始化 README、.gitignore 或 license（我们已经有了）

2. **Git 用户信息**：
   当前配置为：
   - 用户名：`xpc123`
   - 邮箱：`xpc123@users.noreply.github.com`
   
   如需修改：
   ```bash
   git config user.name "你的名字"
   git config user.email "your_email@example.com"
   ```

3. **后续更新**：
   推送后，后续更新代码：
   ```bash
   git add .
   git commit -m "更新说明"
   git push
   ```
