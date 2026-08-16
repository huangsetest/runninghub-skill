---
name: runninghub
description: |
  通过浏览器自动化控制 RunningHub 云端 ComfyUI 平台生成 AI 图片/3D 模型并下载。
  当用户想要：使用 RunningHub 平台文生图/图生图、运行 AI 应用、运行 ComfyUI 工作流、生成图片或 3D 模型后下载时触发。
  用户给一个 runninghub 链接时，自动按 URL 判断用「AI 应用」还是「工作流」逻辑处理。
agent_created: true
---

# RunningHub 云端自动化（AI 应用 + 工作流两套逻辑）

核心思路：**提交任务 → 查询结果接口（`POST /api/output/v2/history`）→ 提取 `fileUrl` → 直接下载**。
不依赖页面下载按钮，也无需 `page.goto` 图片地址（CDN 返回 attachment 头会触发 Download 报错）。

## ⚡ URL 自动判断（用户给链接时先看这里）

| 链接特征 | 走哪套逻辑 | 说明 |
|---|---|---|
| 含 `/ai-detail/` | **AI 应用逻辑**（见下） | 应用页，`.run-cell` 按钮，结果按 `webappId` 过滤 |
| 含 `/workflow/` | **工作流逻辑**（见下） | ComfyUI 编辑器页，头部"运行 Lite/Standard"按钮，结果按 `workflowId` 过滤 |

统一入口脚本：`scripts/rh_run.py <url> [img1] [img2] [outDir]`——脚本自己判断 URL 并走对应逻辑。

## 用户信息

- **邮箱**: aistudent2077@163.com / **163 授权码**: <163邮箱授权码>
- **RunningHub 登录**: phone `<RH手机号>` / password `<RH密码>`（Chrome 已保持会话，一般无需重登）
- **已知应用**（ai-detail 逻辑）:
  - 文生图: `1996843851891580930`（单张 PNG）
  - 一键换装: `2012848202482978818`
  - 图生图·塑型好·高清修复: `2070768165931544577`（参考图槽；**输出 ZIP 打包**）
  - 双图编辑: `2088279378902999042`（4 槽，图1=人物 图2=背景）
- **已知工作流**（workflow 逻辑）:
  - SDXL图生图（含lora+固定种子）: `2088901156960559106`

## 前置条件：连接已登录的 Chrome（端口 9222）

**不要新开浏览器**。Chrome 用 `C:\Users\Administrator\Desktop\chrome.exe.lnk`（`--remote-debugging-port=9222 --user-data-dir=C:\ChromeDebugTmp`）启动，已登录 RunningHub。脚本 CDP 直连：

```python
from playwright.sync_api import sync_playwright
p = sync_playwright().start()
browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
context = browser.contexts[0]   # 共享登录 cookie
page = context.new_page()
```

- Chrome 没起来会 `ECONNREFUSED 127.0.0.1:9222` → 用下面的快捷方式参数重新拉起再跑。
- Playwright 只装 Python 库（`pip install playwright`），不用下 Chromium。
- **云端任务不依赖本地 Chrome**：Chrome 中途挂掉不影响已提交任务，重启调试实例后查结果接口照样能下载。

### Chrome 调试实例：启动 / 卡死重启（重要）

- **启动**：用 PowerShell `Start-Process`（**不要用 Bash `nohup &`**——沙箱会在命令结束时回收子进程，Chrome 直接消失）：
  ```powershell
  Start-Process -FilePath "C:\Users\Administrator\AppData\Local\Google\Chrome\Bin\chrome.exe" `
    -ArgumentList '--remote-debugging-port=9222','--user-data-dir=C:\ChromeDebugTmp','--no-first-run','--no-default-browser-check'
  ```
- **卡死症状**：`connect_over_cdp` 报 `Timeout 180000ms`（WebSocket 连上但协议不响应）；`curl 127.0.0.1:9222/json/version` 却正常。原因常是**调试实例里标签页堆积**（每次脚本 `context.new_page()` 都会留标签，长时间调试后主进程忙不过来）。
- **处理**：只杀 `C:\ChromeDebugTmp` 的进程（别动其他浏览器），再重新启动：
  ```powershell
  Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
    Where-Object { $_.CommandLine -like '*ChromeDebugTmp*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -Confirm:$false }
  ```
  重启后 `/json/version` 的 `webSocketDebuggerUrl` 会变化，属正常。

## 公共部分（两套逻辑共用）

### 鉴权（接口查询必须）

```js
const tok = localStorage.getItem('Rh-Accesstoken') || '';
fetch(path, {method:'POST',
  headers:{'Content-Type':'application/json','authorization':'Bearer '+tok,'user-language':'zh_CN'},
  body: JSON.stringify(payload)}).then(r=>r.json());
```
不带 `authorization` → `403 TOKEN_MISSION`。在页面上下文里 `fetch` 最稳（带同源/Referer）。

### 结果接口

`POST /api/output/v2/history`，payload 分两种（见下）。响应 `data[]` 按时间倒序，字段：`id`、`taskStatus`（SUCCESS/RUNNING/QUEUED/FAILED）、`fileUrl`（CDN 直链）、`outputName`、`workflowId`、`webappId`、`createTime`。
**注意**：不带过滤条件时返回**跨工作流/应用混合列表**，必须按 `workflowId` 或 `webappId` 过滤 + 新任务 id 检测，否则会拿到旧任务/别人的结果。

### 下载（⚠️ 别用 page.goto）

```python
resp = context.request.get(file_url, timeout=120000)   # 共享 cookie、无 CORS
data = resp.body()
```
兜底 `urllib.request.urlopen(file_url).read()`。按魔数处理：
- `89504e47`/`ffd8ff` → PNG/JPG 直接保存
- `PK\x03\x04` → ZIP，`zipfile` 解压取图
- `676c5446` → GLB（glTF 3D 模型），原样保存

---

# 分支 A：AI 应用页（/ai-detail/xxx）

### A1. 打开 + 上传（图生图类）

```python
page.goto(f"https://www.runninghub.cn/ai-detail/{app_id}", wait_until="domcontentloaded", timeout=60000)
page.wait_for_timeout(5000)
slots = page.locator(".media-group-item input[type=file]")
slots.nth(0).set_input_files(img1)      # 图1
slots.nth(1).set_input_files(img2)      # 图2（可选，多图应用）
page.wait_for_timeout(4000)             # 等上传完成
```
- 有槽名时用 `.media-group-item:has-text('<槽名>') input[type=file]`（如"参考图"）
- 槽语义不明时先 dump 槽位/提示词/应用标题确认（参考 `dbg_app*.py` 思路）

### A2. 点运行

```python
page.locator(".run-cell").first.click()   # 运行按钮是 div，文案"立即运行 Standard/Plus"
```

### A3. 轮询结果（webappId 过滤 + 新任务检测）

```python
hist = api(page, "/api/output/v2/history", {"size":20,"current":1,"taskType":["WORKFLOW","WEBAPP"],"webappId":app_id,"fromId":""})
old_ids = {t["id"] for t in hist["data"] if t.get("webappId")==app_id}
# 点击运行后轮询，只认 id 不在 old_ids 且 taskStatus==SUCCESS 且有 fileUrl 的任务
```
⚠️ 同图重跑可能秒返回缓存结果，务必用"新 id"判断，别拿 `data[0]` 就下载。

---

# 分支 B：工作流编辑器页（/workflow/xxx）

### B1. 打开 + 等渲染

```python
page.goto(wf_url, wait_until="domcontentloaded", timeout=60000)
page.wait_for_timeout(22000)   # 运行按钮要 ~20s 才渲染出来！
```

### B2. 点运行（头部按钮）

```python
btn = page.get_by_role("button", name="运行 Lite/Standard", exact=True).first
btn.click()
```
- 头部有 3 个 split 按钮：`运行 Lite/Standard` / `运行 Lite/Plus` / `运行 Ultra·6000D`
- 页面头部任务列表面板里的 **"再次生成" 不是重跑**！它调 `POST /api/creation/workflowRegenerate`，会**新建工作流草稿**。别点它来重跑。

### B3. 轮询结果（workflowId 过滤 + 新任务检测）

```python
hist = api(page, "/api/output/v2/history", {"size":20,"current":1,"taskType":["WORKFLOW","WEBAPP"],"fromId":""})
old_ids = {t["id"] for t in hist["data"] if t.get("workflowId")==wf_id}
# 点击运行后轮询，只认 id 不在 old_ids、workflowId==wf_id、taskStatus==SUCCESS 且有 fileUrl 的任务
```

### B4. 结果可能形态

图片（PNG）、ZIP（解压取图）、GLB（3D）。同样按魔数处理。

---

## 图生图/多图通用注意

- 上传槽选择器通用式：`.media-group-item:has-text('<槽名>') input[type=file]`；无槽名取 `.media-group-item input[type=file]` 第 N 个。
- 多图槽按 `nth()` 顺序对应（图1=槽0、图2=槽1…），槽多时先 dump 语义再传。

## agent-browser 备选路线（同逻辑）

agent-browser 底层是 Playwright-core（CDP）：
```bash
agent-browser connect 9222
agent-browser open <url>
agent-browser network har start   # 录制（等价监听）
# 点运行、等待…
agent-browser network har stop <path>   # 从 HAR 里找 output/v2/history 的 fileUrl
```
页面快照看不到结果是正常的，以接口为准。

## 已知坑（重要）

1. 工作流编辑器右侧"任务列表"面板"预览节点出图不显示在任务列表中 · 暂无数据"——是 ComfyUI 画布预览，不是结果接口。
2. ComfyUI iframe `contentWindow.app.graph` 要 ~10s 就绪；`_nodes` 异步注册，读节点要轮询。
3. 新页面读 SaveImage 节点 `imgs` 是**空的**（WebSocket 缓存，新页面没跑过队列）。拿结果走 `output/v2/history`，不要读节点。
4. `agent-browser eval` 偶尔 `EOF while parsing a value`（daemon 卡住），重试或改用 Playwright CDP。
5. 上传组件是 Ant Design 隐藏 `<input type=file>`，用 `set_input_files`。
6. `git push` 到 GitHub 若卡住无输出：加 `-c credential.helper=` 禁用凭据管理器。
7. 结果接口查询 payload 里带 `webappId` 就只查该应用；不带则全量混合，务必按 `workflowId/webappId` 过滤。

## 参考脚本（均在 scripts/）

- **`rh_run.py <url> [img1] [img2] [outDir]`** —— 统一入口，按 URL 自动走 A/B 逻辑（推荐直接用）
- `rh_run_wf.py <workflow-URL>` —— 分支 B 专用（工作流）
- `rh_run_new.py <ai-detail-URL> <img>` —— 分支 A 专用（带新任务检测）
- `rh_run_with_upload.py <ai-detail-URL> <img>` —— 分支 A 单图上传
- `rh_run_2imgs.py <ai-detail-URL> <img1> <img2>` —— 分支 A 双图上传
- `rh_get_latest.py <appId>` —— 只查最新结果并下载（不提交任务）
- `send_email.py` —— 163 发信
