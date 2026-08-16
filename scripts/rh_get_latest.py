"""
RunningHub：直接查结果接口拿 fileUrl 并下载（不点下载按钮、不 goto 图片）。
用法：python rh_get_latest.py <appId> [--out 目录]
"""
import os, sys, json, time, traceback
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")
CDP = "http://127.0.0.1:9222"
APP_ID = sys.argv[1] if len(sys.argv) > 1 else "1996843851891580930"
OUT_DIR = sys.argv[2] if len(sys.argv) > 2 else r"C:\Users\Administrator\WorkBuddy\2026-08-16-12-08-06\rh_output"
HISTORY_API = "https://www.runninghub.cn/api/output/v2/history"


def fetch_history(page, app_id):
    """在页面上下文里 fetch（带上页面实际使用的 authorization token）"""
    body = page.evaluate("""(appId) => {
        const tok = localStorage.getItem('Rh-Accesstoken') || '';
        return fetch('/api/output/v2/history', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'authorization': 'Bearer ' + tok, 'user-language': 'zh_CN'},
            body: JSON.stringify({size: 20, current: 1, taskType: ['WORKFLOW','WEBAPP'], webappId: appId, fromId: ''})
        }).then(r => r.json());
    }""", app_id)
    return body


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        context = browser.contexts[0]
        page = context.new_page()
        page.goto(f"https://www.runninghub.cn/ai-detail/{APP_ID}", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        # 从结果查询接口拿最新成功任务
        tasks = []
        for attempt in range(10):
            try:
                body = fetch_history(page, APP_ID)
                tasks = body.get("data") or []
            except Exception as e:
                print(f"[!] 查询失败(第{attempt+1}次): {e}", flush=True)
            if tasks:
                break
            page.wait_for_timeout(2000)

        if not tasks:
            raise RuntimeError("结果接口没有返回任务")

        newest = tasks[0]
        print(f"[*] 最新任务: id={newest.get('id')} status={newest.get('taskStatus')} "
              f"createTime={newest.get('createTime')} output={newest.get('outputName')}", flush=True)
        file_url = newest.get("fileUrl")
        if not file_url:
            raise RuntimeError("最新任务没有 fileUrl")

        fname = newest.get("outputName") or os.path.basename(file_url.split("?")[0])
        out_path = os.path.join(OUT_DIR, fname)

        # 下载：先用 context.request.get（共享 cookie、无 CORS 限制），失败再退回 urllib
        data = None
        try:
            resp = context.request.get(file_url, timeout=90000)
            data = resp.body()
        except Exception as e:
            print(f"[!] context.request 下载失败: {e}", flush=True)
        if data is None:
            import urllib.request
            with urllib.request.urlopen(file_url, timeout=90) as r:
                data = r.read()
        with open(out_path, "wb") as f:
            f.write(data)

        size = os.path.getsize(out_path)
        magic = data[:8].hex()
        print(f"[+] 已保存: {out_path} ({size/1024/1024:.2f} MB, {size} B, magic={magic})", flush=True)
        page.close()
        browser.close()
        print(f"RESULT|{out_path}|{size}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
