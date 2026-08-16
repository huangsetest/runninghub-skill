"""
RunningHub：提交后严格取“新任务”结果（避免误拿历史任务）。
用法: python rh_run_new.py <ai-detail-URL> <image-path> [outDir] [timeout]
"""
import os, sys, time, traceback
sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")
from playwright.sync_api import sync_playwright

CDP = "http://127.0.0.1:9222"
APP_URL = sys.argv[1]
IMG_PATH = sys.argv[2]
OUT_DIR = sys.argv[3] if len(sys.argv) > 3 else r"C:\Users\Administrator\WorkBuddy\2026-08-16-12-08-06\rh_output"
TIMEOUT = int(sys.argv[4]) if len(sys.argv) > 4 else 420


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
    app_id = APP_URL.rstrip("/").split("/")[-1]
    os.makedirs(OUT_DIR, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        context = browser.contexts[0]
        page = context.new_page()
        page.goto(APP_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(6000)

        # 提交前的最新任务 id（用来识别“新任务”）
        hist = api(page, "/api/output/v2/history", {"size": 5, "current": 1, "taskType": ["WORKFLOW", "WEBAPP"], "webappId": app_id, "fromId": ""})
        old_ids = {t.get("id") for t in (hist.get("data") or [])}
        print(f"[*] 提交前已有任务数: {len(old_ids)}", flush=True)

        # 上传槽0
        slot = page.locator(".media-group-item:has-text('参考图') input[type=file]").first
        if slot.count() == 0:
            slot = page.locator(".media-group-item input[type=file]").first
        print(f"[*] 上传 -> {IMG_PATH}", flush=True)
        slot.set_input_files(IMG_PATH)
        page.wait_for_timeout(4000)

        run_btn = page.locator(".run-cell").first
        print(f"[*] 点击运行: {run_btn.inner_text().strip()[:30]!r}", flush=True)
        run_btn.click()

        # 轮询：找新任务 id（不在 old_ids 里），等 SUCCESS
        start = time.time()
        new_task = None
        while time.time() - start < TIMEOUT:
            try:
                h = api(page, "/api/output/v2/history", {"size": 10, "current": 1, "taskType": ["WORKFLOW", "WEBAPP"], "webappId": app_id, "fromId": ""})
                tasks = h.get("data") or []
                new_candidates = [t for t in tasks if t.get("id") not in old_ids]
                if new_candidates:
                    t = new_candidates[0]
                    st = t.get("taskStatus")
                    print(f"    [{int(time.time()-start)}s] 新任务 {t.get('id')} status={st} created={t.get('createTime')}", flush=True)
                    if st == "SUCCESS" and t.get("fileUrl"):
                        new_task = t
                        break
                    if st in ("FAILED", "ERROR"):
                        raise RuntimeError(f"任务失败: {st} {t.get('taskResultDesc')}")
                else:
                    # 也许还没出现在 history，查 running 列表
                    try:
                        r = api(page, "/task/list", {"size": 6, "current": 1, "taskStatus": ["RUNNING", "QUEUED"], "taskType": ["WORKFLOW", "WEBAPP"], "webappId": app_id})
                        run_tasks = r.get("data") or []
                        for rt in run_tasks:
                            if rt.get("id") not in old_ids:
                                print(f"    [{int(time.time()-start)}s] 排队/运行中: {rt.get('id')} {rt.get('taskStatus')}", flush=True)
                    except Exception as e:
                        pass
            except RuntimeError:
                raise
            except Exception as e:
                print(f"[!] 查询失败: {e}", flush=True)
            time.sleep(5)

        if not new_task:
            raise RuntimeError("未发现新任务（提交可能失败）")

        file_url = new_task["fileUrl"]
        fname = new_task.get("outputName") or os.path.basename(file_url.split("?")[0])
        out_path = os.path.join(OUT_DIR, fname)
        print(f"[*] 下载 -> {out_path}", flush=True)
        resp = context.request.get(file_url, timeout=120000)
        data = resp.body()
        with open(out_path, "wb") as f:
            f.write(data)
        print(f"[+] 已保存: {out_path} ({len(data)/1024/1024:.2f} MB, magic={data[:4].hex()})", flush=True)
        page.close()
        browser.close()
        print(f"RESULT|{out_path}|{len(data)}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
