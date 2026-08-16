"""
RunningHub 工作流编辑器页：点头部"运行"按钮 -> 按 workflowId 过滤监听新任务 -> 下载。
用法: python rh_run_wf.py <workflow-URL> [outDir] [timeout]
"""
import os, sys, time, zipfile, traceback
sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")
from playwright.sync_api import sync_playwright

CDP = "http://127.0.0.1:9222"
WF_URL = sys.argv[1]
OUT_DIR = sys.argv[2] if len(sys.argv) > 2 else r"C:\Users\Administrator\WorkBuddy\2026-08-16-12-08-06\rh_output"
TIMEOUT = int(sys.argv[3]) if len(sys.argv) > 3 else 420
RUN_MODE = "运行 Lite/Standard"  # 可改: 运行 Lite/Plus / 运行 Ultra·6000D


def api(page, path, payload):
    return page.evaluate("""({path, payload}) => {
        const tok = localStorage.getItem('Rh-Accesstoken') || '';
        return fetch(path, {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'authorization': 'Bearer ' + tok, 'user-language': 'zh_CN'},
            body: JSON.stringify(payload)
        }).then(r => r.json());
    }""", {"path": path, "payload": payload})


def main():
    wf_id = WF_URL.rstrip("/").split("/")[-1]
    os.makedirs(OUT_DIR, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        context = browser.contexts[0]
        page = context.new_page()
        page.goto(WF_URL, wait_until="domcontentloaded", timeout=60000)
        print("[*] 等待页面渲染（运行按钮约 20s 出现）...", flush=True)
        page.wait_for_timeout(22000)

        # 运行按钮：按精确文本找 BUTTON
        btn = page.get_by_role("button", name=RUN_MODE, exact=True).first
        if btn.count() == 0:
            # 退路：文本包含"运行"的第一个按钮
            btn = page.locator("button").filter(has_text="运行").first
        print(f"[*] 运行按钮: {btn.inner_text().strip()[:30]!r}", flush=True)
        btn.click()

        # 提交前的本工作流任务 id
        hist = api(page, "/api/output/v2/history", {"size": 20, "current": 1, "taskType": ["WORKFLOW", "WEBAPP"], "fromId": ""})
        old_ids = {t.get("id") for t in (hist.get("data") or []) if t.get("workflowId") == wf_id}
        print(f"[*] 本工作流已有任务: {len(old_ids)}", flush=True)

        start = time.time()
        new_task = None
        while time.time() - start < TIMEOUT:
            try:
                h = api(page, "/api/output/v2/history", {"size": 20, "current": 1, "taskType": ["WORKFLOW", "WEBAPP"], "fromId": ""})
                cands = [t for t in (h.get("data") or [])
                         if t.get("workflowId") == wf_id and t.get("id") not in old_ids]
                if cands:
                    t = cands[0]
                    st = t.get("taskStatus")
                    print(f"    [{int(time.time()-start)}s] 新任务 {t.get('id')} status={st} out={t.get('outputName')}", flush=True)
                    if st == "SUCCESS" and t.get("fileUrl"):
                        new_task = t
                        break
                    if st in ("FAILED", "ERROR"):
                        raise RuntimeError(f"任务失败: {st}")
            except RuntimeError:
                raise
            except Exception as e:
                print(f"[!] 查询失败: {e}", flush=True)
            time.sleep(5)

        if not new_task:
            raise RuntimeError("未发现本工作流的新任务")

        file_url = new_task["fileUrl"]
        fname = new_task.get("outputName") or os.path.basename(file_url.split("?")[0])
        out_path = os.path.join(OUT_DIR, fname)
        print(f"[*] 下载 -> {out_path}", flush=True)
        resp = context.request.get(file_url, timeout=120000)
        data = resp.body()
        with open(out_path, "wb") as f:
            f.write(data)
        print(f"[+] 已保存: {out_path} ({len(data)/1024/1024:.2f} MB, magic={data[:4].hex()})", flush=True)

        if data[:4] == b"PK\x03\x04":
            ex = os.path.join(OUT_DIR, os.path.splitext(fname)[0])
            os.makedirs(ex, exist_ok=True)
            with zipfile.ZipFile(out_path) as z:
                z.extractall(ex)
            for root, _, files in os.walk(ex):
                for f in files:
                    print(f"    解压: {os.path.join(root, f)}", flush=True)
        page.close()
        browser.close()
        print(f"RESULT|{out_path}|{len(data)}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
