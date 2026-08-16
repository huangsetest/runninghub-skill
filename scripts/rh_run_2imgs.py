"""
RunningHub 双图应用：上传图1(人物)图2(背景) -> 运行 -> 结果接口 -> 下载(自动解压 zip)。
用法: python rh_run_2imgs.py <ai-detail-URL> <img1> <img2> [outDir]
"""
import os, sys, time, zipfile, traceback
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")
CDP = "http://127.0.0.1:9222"
APP_URL = sys.argv[1]
IMG1 = sys.argv[2]
IMG2 = sys.argv[3]
OUT_DIR = sys.argv[4] if len(sys.argv) > 4 else r"C:\Users\Administrator\WorkBuddy\2026-08-16-12-08-06\rh_output"
TIMEOUT = 360


def fetch_history(page, app_id):
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
    app_id = APP_URL.rstrip("/").split("/")[-1]
    os.makedirs(OUT_DIR, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        context = browser.contexts[0]
        page = context.new_page()
        print(f"[*] 打开应用页: {APP_URL}", flush=True)
        page.goto(APP_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(6000)

        slots = page.locator(".media-group-item input[type=file]")
        n = slots.count()
        print(f"[*] 图片槽数量: {n}", flush=True)
        print(f"[*] 上传 槽0(人物) <- {IMG1}", flush=True)
        slots.nth(0).set_input_files(IMG1)
        page.wait_for_timeout(3000)
        if n > 1:
            print(f"[*] 上传 槽1(背景) <- {IMG2}", flush=True)
            slots.nth(1).set_input_files(IMG2)
            page.wait_for_timeout(3000)

        run_btn = page.locator(".run-cell").first
        print(f"[*] 运行按钮: {run_btn.inner_text().strip()[:40]!r}", flush=True)
        run_btn.click()
        print("[*] 已点击运行，轮询结果接口...", flush=True)

        start = time.time()
        file_url = None
        while time.time() - start < TIMEOUT:
            try:
                body = fetch_history(page, app_id)
                tasks = body.get("data") or []
                if tasks:
                    t = tasks[0]
                    if t.get("taskStatus") == "SUCCESS" and t.get("fileUrl"):
                        file_url = t["fileUrl"]
                        print(f"[+] SUCCESS: {t.get('outputName')} created={t.get('createTime')}", flush=True)
                        break
                    print(f"    status={t.get('taskStatus')} ...", flush=True)
            except Exception as e:
                print(f"[!] 查询失败: {e}", flush=True)
            time.sleep(3)

        if not file_url:
            raise RuntimeError("超时未拿到结果")

        fname = os.path.basename(file_url.split("?")[0]) or f"result_{int(time.time())}.png"
        out_path = os.path.join(OUT_DIR, fname)
        print(f"[*] 下载 -> {out_path}", flush=True)
        data = None
        try:
            resp = context.request.get(file_url, timeout=90000)
            data = resp.body()
        except Exception as e:
            print(f"[!] context.request 失败: {e}", flush=True)
        if data is None:
            import urllib.request
            with urllib.request.urlopen(file_url, timeout=90) as r:
                data = r.read()
        with open(out_path, "wb") as f:
            f.write(data)
        size = os.path.getsize(out_path)
        print(f"[+] 已保存: {out_path} ({size/1024/1024:.2f} MB, magic={data[:4].hex()})", flush=True)

        # zip 自动解压
        if data[:4] == b"PK\x03\x04":
            ex_dir = os.path.join(OUT_DIR, os.path.splitext(fname)[0])
            os.makedirs(ex_dir, exist_ok=True)
            with zipfile.ZipFile(out_path) as z:
                z.extractall(ex_dir)
            imgs = [os.path.join(ex_dir, f) for f in os.listdir(ex_dir) if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]
            print(f"[+] 解压出 {len(imgs)} 张图:", flush=True)
            for im in imgs:
                print("    ", im, os.path.getsize(im), "B", flush=True)
            if imgs:
                out_path = imgs[0]
        page.close()
        browser.close()
        print(f"RESULT|{out_path}|{size}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
