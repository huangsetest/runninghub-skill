"""
RunningHub 统一入口：按 URL 自动分流。
  /ai-detail/ -> AI 应用逻辑（上传可选 -> .run-cell -> webappId 过滤轮询 -> 下载）
  /workflow/  -> 工作流逻辑（头部运行按钮 -> workflowId 过滤轮询 -> 下载）
用法: python rh_run.py <url> [img1] [img2] [outDir]
"""
import os, sys, time, zipfile, traceback
sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")
from playwright.sync_api import sync_playwright

CDP = "http://127.0.0.1:9222"
URL = sys.argv[1]
IMG1 = sys.argv[2] if len(sys.argv) > 2 else None
IMG2 = sys.argv[3] if len(sys.argv) > 3 else None
OUT_DIR = sys.argv[4] if len(sys.argv) > 4 else r"C:\Users\Administrator\WorkBuddy\2026-08-16-12-08-06\rh_output"
TIMEOUT = 420


def api(page, path, payload):
    return page.evaluate("""({path, payload}) => {
        const tok = localStorage.getItem('Rh-Accesstoken') || '';
        return fetch(path, {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'authorization': 'Bearer ' + tok, 'user-language': 'zh_CN'},
            body: JSON.stringify(payload)
        }).then(r => r.json());
    }""", {"path": path, "payload": payload})


def save_result(context, file_url, out_dir):
    resp = context.request.get(file_url, timeout=120000)
    data = resp.body()
    fname = os.path.basename(file_url.split("?")[0]) or f"r_{int(time.time())}.bin"
    out_path = os.path.join(out_dir, fname)
    with open(out_path, "wb") as f:
        f.write(data)
    print(f"[+] 已保存: {out_path} ({len(data)/1024/1024:.2f} MB, magic={data[:4].hex()})", flush=True)
    if data[:4] == b"PK\x03\x04":
        ex = os.path.join(out_dir, os.path.splitext(fname)[0])
        os.makedirs(ex, exist_ok=True)
        with zipfile.ZipFile(out_path) as z:
            z.extractall(ex)
        for root, _, files in os.walk(ex):
            for f in files:
                print(f"    解压: {os.path.join(root, f)}", flush=True)
    return out_path, data


def poll_new_task(page, kind, owner_id, old_ids):
    """轮询 output/v2/history，返回新任务 dict；kind: workflow/webapp"""
    start = time.time()
    while time.time() - start < TIMEOUT:
        try:
            h = api(page, "/api/output/v2/history", {"size": 20, "current": 1, "taskType": ["WORKFLOW", "WEBAPP"], "fromId": ""})
            cands = [t for t in (h.get("data") or [])
                     if t.get("workflowId" if kind == "workflow" else "webappId") == owner_id
                     and t.get("id") not in old_ids]
            if cands:
                t = cands[0]
                st = t.get("taskStatus")
                print(f"    [{int(time.time()-start)}s] 新任务 {t.get('id')} status={st} out={t.get('outputName')}", flush=True)
                if st == "SUCCESS" and t.get("fileUrl"):
                    return t
                if st in ("FAILED", "ERROR"):
                    raise RuntimeError(f"任务失败: {st}")
            # 顺便看排队/运行中的任务
            try:
                r = api(page, "/task/list", {"size": 6, "current": 1, "taskStatus": ["RUNNING", "QUEUED"], "taskType": ["WORKFLOW", "WEBAPP"]})
                for rt in (r.get("data") or []):
                    if rt.get("id") not in old_ids:
                        print(f"    [{int(time.time()-start)}s] 排队/运行中: {rt.get('id')} {rt.get('taskStatus')}", flush=True)
            except Exception:
                pass
        except RuntimeError:
            raise
        except Exception as e:
            print(f"[!] 查询失败: {e}", flush=True)
        time.sleep(5)
    raise RuntimeError("超时未发现新任务")


def run_workflow(page, context, wf_id, out_dir):
    page.wait_for_timeout(22000)  # 运行按钮 ~20s 渲染
    btn = page.get_by_role("button", name="运行 Lite/Standard", exact=True).first
    if btn.count() == 0:
        btn = page.locator("button").filter(has_text="运行").first
    print(f"[*] [工作流] 运行按钮: {btn.inner_text().strip()[:30]!r}", flush=True)
    btn.click()
    h = api(page, "/api/output/v2/history", {"size": 20, "current": 1, "taskType": ["WORKFLOW", "WEBAPP"], "fromId": ""})
    old_ids = {t.get("id") for t in (h.get("data") or []) if t.get("workflowId") == wf_id}
    print(f"[*] [工作流] 已有任务: {len(old_ids)}", flush=True)
    t = poll_new_task(page, "workflow", wf_id, old_ids)
    return save_result(context, t["fileUrl"], out_dir)


def run_app(page, context, app_id, out_dir):
    page.wait_for_timeout(5000)
    slots = page.locator(".media-group-item input[type=file]")
    n = slots.count()
    print(f"[*] [应用] 图片槽数: {n}", flush=True)
    if IMG1:
        print(f"[*] [应用] 槽0 <- {IMG1}", flush=True)
        slots.nth(0).set_input_files(IMG1)
        page.wait_for_timeout(3000)
    if IMG2 and n > 1:
        print(f"[*] [应用] 槽1 <- {IMG2}", flush=True)
        slots.nth(1).set_input_files(IMG2)
        page.wait_for_timeout(3000)
    run_btn = page.locator(".run-cell").first
    print(f"[*] [应用] 运行按钮: {run_btn.inner_text().strip()[:30]!r}", flush=True)
    run_btn.click()
    h = api(page, "/api/output/v2/history", {"size": 20, "current": 1, "taskType": ["WORKFLOW", "WEBAPP"], "webappId": app_id, "fromId": ""})
    old_ids = {t.get("id") for t in (h.get("data") or []) if t.get("webappId") == app_id}
    print(f"[*] [应用] 已有任务: {len(old_ids)}", flush=True)
    t = poll_new_task(page, "webapp", app_id, old_ids)
    return save_result(context, t["fileUrl"], out_dir)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        context = browser.contexts[0]
        page = context.new_page()
        print(f"[*] 打开: {URL}", flush=True)
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)

        if "/workflow/" in URL:
            wf_id = URL.rstrip("/").split("/")[-1]
            out_path, data = run_workflow(page, context, wf_id, OUT_DIR)
        elif "/ai-detail/" in URL:
            app_id = URL.rstrip("/").split("/")[-1]
            out_path, data = run_app(page, context, app_id, OUT_DIR)
        else:
            raise RuntimeError("无法识别 URL 类型（需含 /workflow/ 或 /ai-detail/）")

        page.close()
        browser.close()
        print(f"RESULT|{out_path}|{len(data)}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
