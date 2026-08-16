---
name: runninghub
description: |
  通过浏览器自动化控制 RunningHub 云端 ComfyUI 平台生成 AI 图片并发送到邮箱。
  当用户想要：使用 RunningHub 平台文生图、通过浏览器操作云端 ComfyUI、生成图片后下载或发邮箱时触发。
agent_created: true
---

# RunningHub 云端文生图自动化

核心思路：**提交任务 → 监听/查询结果接口（`/api/output/v2/history`）→ 提取 `fileUrl` → 直接下载**。
不依赖页面上的下载按钮，也无需 `page.goto` 图片地址。

## 用户信息

- **邮箱**: aistudent2077@163.com
- **邮箱授权码**: <163邮箱授权码>
- **RunningHub 登录**: phone `<RH手机号>` / password `<RH密码>`（一般无需重新登录，Chrome 已保持会话）
- **已知应用**:
  - 文生图应用: `https://www.runninghub.cn/ai-detail/1996843851891580930`（输出单张 PNG）
  - 一键换装应用: `https://www.runninghub.cn/zh-cn/ai-detail/2012848202482978818`
  - 图生图·塑型好·高清修复: `https://www.runninghub.cn/ai-detail/2070768165931544577`（参考图槽 + 提示词默认"古装典雅女子"；**输出为 ZIP 打包**，约 19 RH/次）
  - 双图编辑（人物+背景合成）: `https://www.runninghub.cn/ai-detail/2088279378902999042`（**4 个图片槽**，图1=人物 图2=背景，默认提示词"图1的背景变成图2的原本场景，人物保持不变"；输出单张 PNG，运行 Plus）

## 前置条件：连接已登录的 Chrome（端口 9222）

**不要新开浏览器**。用桌面快捷方式 `C:\Users\Administrator\Desktop\chrome.exe.lnk`（`--remote-debugging-port=9222 --user-data-dir=C:\ChromeDebugTmp`）启动，已登录 RunningHub。脚本通过 CDP 直连：

```python
from playwright.sync_api import sync_playwright
p = sync_playwright().start()
browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
context = browser.contexts[0]   # 共享登录 cookie
page = context.new_page()
```

Playwright 只装 Python 库即可（`pip install playwright`，不用 `playwright install` 下 Chromium）。

## 标准流程（AI 应用页 /ai-detail/xxx）

### 1. 打开应用页并点运行

```python
page.goto("https://www.runninghub.cn/ai-detail/<appId>", wait_until="domcontentloaded", timeout=60000)
page.wait_for_timeout(5000)
run_btn = page.locator(".run-cell").first   # 运行按钮是 div，不是 button
run_btn.click()
```

运行按钮选择器：`.run-cell`（通用）、`.run-cell--standard`、`.run-cell--plus`（换装应用）。文案如"立即运行 Standard"。

### 2. 查询结果接口（关键）

```python
body = page.evaluate("""(appId) => {
    const tok = localStorage.getItem('Rh-Accesstoken') || '';
    return fetch('/api/output/v2/history', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'authorization': 'Bearer ' + tok, 'user-language': 'zh_CN'},
        body: JSON.stringify({size: 20, current: 1, taskType: ['WORKFLOW','WEBAPP'], webappId: appId, fromId: ''})
    }).then(r => r.json());
}""", app_id)
task = body["data"][0]          # 最新任务在最前
file_url = task["fileUrl"]      # CDN 直链
status   = task["taskStatus"]   # SUCCESS / RUNNING / QUEUED / FAILED
```

**必须**带 `authorization: Bearer <localStorage.Rh-Accesstoken>` + `user-language: zh_CN`，否则返回 `403 TOKEN_MISSION`。在页面内 `fetch` 最稳（自动带同源/Referer）。

### 3. 轮询到完成

间隔 2s 重查 history，直到最新任务 `taskStatus == "SUCCESS"` 且有 `fileUrl`；超时（默认 5 分钟）报错。

### 4. 直接下载（⚠️ 别用 page.goto）

CDN 会返回 `Content-Disposition: attachment`，`page.goto(图片URL)` 会抛 `Error: Download is starting`。正确方式：

```python
resp = context.request.get(file_url, timeout=90000)   # 共享 cookie、无 CORS 限制
data = resp.body()
with open(out_path, "wb") as f:
    f.write(data)
```

兜底：`urllib.request.urlopen(file_url).read()`。

### 5. 发送邮件（163）

SMTP_SSL `smtp.163.com:465`，发件/收件 `aistudent2077@163.com`，授权码 `<163邮箱授权码>`，附件 MIMEImage/MIMEApplication。

## 图生图应用：先上传"参考图"再运行

应用页常见图片槽（如"参考图"）。上传用 Ant Design 隐藏 file input：

```python
slot = page.locator(".media-group-item:has-text('参考图') input[type=file]").first
slot.set_input_files(r"C:\path\to\image.jpg")
page.wait_for_timeout(4000)   # 等上传完成
run_btn = page.locator(".run-cell").first
run_btn.click()
```

- 槽选择器通用式：`.media-group-item:has-text('<槽名>') input[type=file]`；无槽名时取 `.media-group-item input[type=file]` 的**第 N 个**（按槽位顺序）。
- 完成后同样轮询 `output/v2/history` 拿 `fileUrl`。

## 多图应用（双图编辑等）

槽位按 `nth()` 顺序对应：图1=槽0、图2=槽1……用 `slots.nth(i).set_input_files(路径)` 逐个上传（槽多时先确认语义，比如双图编辑默认"图1背景变图2场景，人物不变"）。运行、轮询、下载同前，脚本见 `scripts/rh_run_2imgs.py <URL> <img1> <img2> [outDir]`。

## ZIP 打包输出（部分应用）

部分工作流把结果打成 **.zip** 返回（`fileUrl` 以 `.zip` 结尾，魔数 `PK`）。下载后需解压取图：

```python
import zipfile
if data[:4] == b"PK\x03\x04":
    open(tmp_zip, "wb").write(data)
    with zipfile.ZipFile(tmp_zip) as z:
        z.extractall(out_dir)   # 解出 image_xxxx.png 等
```

## agent-browser 备选路线（同逻辑）

agent-browser 底层是 Playwright-core（CDP），思路一样：

```bash
agent-browser connect 9222
agent-browser open <url>
agent-browser network har start    # 开始录制（等价于监听）
# …点击运行、等待…
agent-browser network har stop <path>
```

从 HAR 里找 `/api/output/v2/history` 响应 JSON 的 `fileUrl`，再直接下载。**页面快照(snapshot)看不到结果**是正常的，以接口为准。

## 已知坑（重要）

1. **工作流编辑器页**（`/workflow/xxx`）右侧"任务列表"面板显示"预览节点出图不显示在任务列表中 · 暂无数据"——那是 ComfyUI 画布的预览，不是结果接口。
2. ComfyUI iframe 的 `contentWindow.app.graph` 要 **~10 秒**才就绪；`_nodes` 是异步注册的，读节点要轮询等待。
3. 新开页面读 SaveImage 节点（`node.imgs`）是**空的**——`imgs` 是跑队列时 WebSocket 推送的缓存，新页面没跑过队列就没有。要拿结果走 `output/v2/history` 接口，不要读节点。
4. `agent-browser eval` 偶尔报 `EOF while parsing a value`（daemon 卡住），重试或改用 Playwright CDP。
5. 上传组件是 Ant Design，隐藏 `<input type=file>`，用 `set_input_files` 或 `input[type=file]` 选择器。
6. 任务状态接口：页面轮询 `POST /task/list`（`taskStatus:["RUNNING","QUEUED"]`）；结果用 `output/v2/history`。

## 参考脚本

- 通用"查最新结果并下载"：`scripts/rh_get_latest.py <appId> [outDir]`（逻辑即上文第 2–4 步，已在本工作区验证可用）
- 通用"上传+运行+下载"：`scripts/rh_run_with_upload.py <ai-detail-URL> <image-path> [outDir]`（单图槽应用用）
- 通用"双图/多图上传+运行+下载"：`scripts/rh_run_2imgs.py <ai-detail-URL> <img1> <img2> [outDir]`（槽位按 nth 顺序，自动解压 zip）
- 一键换装：见 `runninghub-outfit-change` skill
