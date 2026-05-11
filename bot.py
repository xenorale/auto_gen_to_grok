import csv
import time
import os
import sys
import traceback
import subprocess
import socket
import base64
import re
import threading
import random
import json
from playwright.sync_api import sync_playwright, Page
from playwright_stealth import stealth_sync

CONFIG_FILE = "config.json"

def load_config():
    defaults = {
        "chrome_path": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "user_data_dir": r"C:\chrome_debug_profile",
        "debug_port": 9222,
        "stealth_mode": True
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return {**defaults, **json.load(f)}
        except: pass
    return defaults

runtime_config = load_config()

BASE_DIR = os.getcwd()
PHOTO_PATH = os.path.join(BASE_DIR, "photo")
VIDEO_PATH = os.path.join(BASE_DIR, "video")
CHARS_CSV = os.path.join(BASE_DIR, "characters.csv")
SCENES_CSV = os.path.join(BASE_DIR, "scenes.csv")
PROGRESS_FILE = os.path.join(BASE_DIR, "progress.json")

for d in [PHOTO_PATH, VIDEO_PATH]:
    if not os.path.exists(d): os.makedirs(d)

def get_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r") as f:
                return json.load(f)
        except: pass
    return {"chars": [], "scenes": [], "videos": []}

def commit_progress(category, item_id):
    data = get_progress()
    if item_id not in data[category]:
        data[category].append(item_id)
        with open(PROGRESS_FILE, "w") as f:
            json.dump(data, f, indent=4)

def jitter(a=1.5, b=3.5):
    time.sleep(random.uniform(a, b))

def bridge_connection():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('localhost', 9222)) == 0: return True
    except: pass
    subprocess.Popen(f'"{runtime_config["chrome_path"]}" --remote-debugging-port=9222 --user-data-dir="{runtime_config["user_data_dir"]}"', shell=True)
    time.sleep(5)
    return True

def sync_browser_context(page: Page):
    try:
        page.goto("https://grok.com/imagine", wait_until="commit", timeout=30000)
    except: pass

def set_workflow_mode(page: Page, mode: str):
    label = "Видео" if mode == "video" else "Изображение"
    alt = "Video" if mode == "video" else "Image"
    try:
        selector = f'xpath=//button[text()="{label}" or text()="{alt}"] | //div[@role="button"][text()="{label}" or text()="{alt}"] | //span[text()="{label}" or text()="{alt}"]'
        target = page.locator(selector).first
        if target.is_visible(timeout=5000):
            target.click()
            time.sleep(1)
            return True
    except: pass
    return False

def dispatch_prompt(page: Page, content: str, aspect_ratio: str):
    try:
        final_query = re.sub(r"--ar\s+\S+", f"--ar {aspect_ratio}", content) if "--ar" in content else f"{content.strip()} --ar {aspect_ratio}"
        area = page.locator('textarea, [contenteditable="true"]').first
        area.wait_for(state="visible", timeout=10000)
        area.click()
        area.fill(final_query)
        time.sleep(0.5)
        page.keyboard.press("Enter")
        return True
    except: return False

def attach_asset(page: Page, path: str):
    if not os.path.exists(path): return False
    try:
        page.wait_for_selector('input[type="file"], [role="button"]', timeout=5000)
        inp = page.locator('input[type="file"]')
        if inp.count() > 0:
            inp.first.set_input_files(path)
            return True
        page.get_by_role("button", name=re.compile(r"upload|attach|file|image", re.IGNORECASE)).first.click()
        page.wait_for_selector('input[type="file"]', timeout=3000)
        page.locator('input[type="file"]').first.set_input_files(path)
        return True
    except:
        try:
            page.set_input_files('input[type="file"]', path)
            return True
        except: return False

def inject_persistence_layer(page: Page, identifier: str):
    script = f"""
    (() => {{
        const setup = () => {{
            if (!document.body) return;
            let el = document.getElementById('bot-persist-trigger');
            const ui_text = '📸 SAVE {identifier}';
            if (el) {{
                if (el.getAttribute('data-id') !== '{identifier}') {{
                    el.setAttribute('data-id', '{identifier}');
                    el.setAttribute('data-label', ui_text);
                    if (!el.innerText.includes('⏳') && !el.innerText.includes('✅')) el.innerText = ui_text;
                }}
                return;
            }}
            el = document.createElement('button');
            el.id = 'bot-persist-trigger';
            el.setAttribute('data-id', '{identifier}');
            el.setAttribute('data-label', ui_text);
            el.innerText = ui_text;
            el.style = 'position:fixed; bottom:20px; left:20px; z-index:10000; background:#ffcc00; color:black; padding:12px 20px; border:2px solid black; font-weight:bold; cursor:pointer; border-radius:8px; font-family:sans-serif;';
            el.onclick = (e) => {{
                const nodes = Array.from(document.querySelectorAll('img, video')).filter(n => n.offsetWidth > 200);
                if (nodes.length === 0) return;
                const best = nodes.sort((a, b) => {{
                    if (a.tagName === 'VIDEO' && b.tagName !== 'VIDEO') return -1;
                    if (a.tagName !== 'VIDEO' && b.tagName === 'VIDEO') return 1;
                    return (b.offsetWidth * b.offsetHeight) - (a.offsetWidth * a.offsetHeight);
                }})[0];
                document.querySelectorAll('#bot-active-node').forEach(n => n.id = '');
                best.id = 'bot-active-node';
                el.innerText = '⏳ PROCESSING...';
            }};
            document.body.appendChild(el);
        }};
        setInterval(setup, 1000);
        setup();
    }})();
    """
    page.add_init_script(script)
    try: page.evaluate(script)
    except: pass

def capture_media(page: Page, name: str, category: str):
    try:
        anchor = page.locator("#bot-active-node")
        if anchor.count() > 0:
            payload = page.evaluate("""async () => {
                const el = document.getElementById('bot-active-node');
                if (!el) return null;
                const tag = el.tagName;
                let src = el.src || '';
                if (tag === 'VIDEO' && (!src || src.startsWith('blob:'))) {
                    const s = el.querySelector('source');
                    if (s) src = s.src || src;
                }
                try {
                    const r = await fetch(src);
                    if (r.ok) {
                        const b = await r.blob();
                        const b64 = await new Promise(res => {
                            const f = new FileReader();
                            f.onloadend = () => res(f.result.split(',')[1]);
                            f.readAsDataURL(b);
                        });
                        return { b64, mime: b.type, tag };
                    }
                } catch {}
                return { src, tag };
            }""")
            if not payload: return False
            
            is_vid = payload.get('tag') == 'VIDEO'
            ext = ".mp4" if is_vid else ".jpg"
            if "webp" in payload.get('mime', ''): ext = ".webp"
            
            dest = VIDEO_PATH if (is_vid or name.startswith("video_")) else PHOTO_PATH
            full_path = os.path.join(dest, f"{name}{ext}")
            
            if payload.get('b64'):
                with open(full_path, "wb") as f:
                    f.write(base64.b64decode(payload['b64']))
            else:
                r = page.context.request.get(payload['src'])
                if r.ok:
                    with open(full_path, "wb") as f:
                        f.write(r.body())
            
            commit_progress(category, name)
            page.evaluate("const b = document.getElementById('bot-persist-trigger'); if(b) { b.style.background='#00ff00'; b.innerText='✅ DONE'; }")
            return True
    except: pass
    return False

def sync_previews(pages, names, callback):
    if not callback: return
    for i, page in enumerate(pages):
        try:
            data = page.evaluate("""async () => {
                const nodes = Array.from(document.querySelectorAll('img, video')).filter(n => 
                    n.offsetWidth > 200 && !n.hasAttribute('data-preview-synced')
                );
                if (nodes.length === 0) return null;
                const best = nodes.sort((a, b) => {
                    if (a.tagName === 'VIDEO' && b.tagName !== 'VIDEO') return -1;
                    return (b.offsetWidth * b.offsetHeight) - (a.offsetWidth * a.offsetHeight);
                })[0];
                best.setAttribute('data-preview-synced', 'true');
                try {
                    const r = await fetch(best.src || best.querySelector('source')?.src);
                    const b = await r.blob();
                    const b64 = await new Promise(res => {
                        const f = new FileReader();
                        f.onloadend = () => res(f.result.split(',')[1]);
                        f.readAsDataURL(b);
                    });
                    return { b64, is_vid: best.tagName === 'VIDEO' };
                } catch { return { src: best.src, is_vid: best.tagName === 'VIDEO' }; }
            }""")
            if data:
                callback(names[i], data.get('b64') or data.get('src'), data['is_vid'])
        except: pass

def orchestrate_session(pages, names, category, ui_bridge=None):
    kill_switch = threading.Event()
    commands = []
    
    def internal_sync(n, d, v):
        if ui_bridge:
            if n:
                res = ui_bridge(n, d, v)
                if res: commands.append(res)
            else:
                res = ui_bridge(None, None, None)
                if res: commands.append(res)

    def watcher():
        input()
        kill_switch.set()
    
    threading.Thread(target=watcher, daemon=True).start()
    
    while not kill_switch.is_set():
        internal_sync(None, None, None)
        while commands:
            cmd = commands.pop(0)
            if cmd['name'] in names:
                idx = names.index(cmd['name'])
                p = pages[idx]
                if cmd['action'] == 'save':
                    p.evaluate("const n = Array.from(document.querySelectorAll('img, video')).filter(el => el.offsetWidth > 200).sort((a,b) => b.offsetWidth*b.offsetHeight - a.offsetWidth*a.offsetHeight)[0]; if(n) n.id='bot-active-node';")
                    capture_media(p, cmd['name'], category)
                elif cmd['action'] == 'regen':
                    p.bring_to_front()
                    p.keyboard.press("Enter")
                    p.evaluate("document.querySelectorAll('[data-preview-synced]').forEach(n => n.removeAttribute('data-preview-synced'))")

        for i, p in enumerate(pages): capture_media(p, names[i], category)
        sync_previews(pages, names, internal_sync)
        time.sleep(0.5)

def main(progress_callback=None, ui_bridge=None):
    try:
        bridge_connection()
        state = get_progress()
        with sync_playwright() as pw:
            session = pw.chromium.connect_over_cdp(f"http://localhost:9222")
            ctx = session.contexts[0]
            
            chars = list(csv.DictReader(open(CHARS_CSV, encoding='utf-8')))
            scenes = list(csv.DictReader(open(SCENES_CSV, encoding='utf-8')))
            total = len(chars) + len(scenes) * 2
            counter = 0

            def bump():
                nonlocal counter
                counter += 1
                if progress_callback: progress_callback(counter / total)

            active_tabs, active_names = [], []
            for c in chars:
                if any(os.path.exists(os.path.join(PHOTO_PATH, f"{c['char_id']}{e}")) for e in [".jpg", ".webp", ".png"]) or c['char_id'] in state['chars']:
                    bump()
                    continue
                t = ctx.new_page()
                if runtime_config["stealth_mode"]: stealth_sync(t)
                active_tabs.append(t); active_names.append(c['char_id'])
                sync_browser_context(t)
                inject_persistence_layer(t, c['char_id'])
                set_workflow_mode(t, "image")
                jitter(1, 2)
                dispatch_prompt(t, c['char_prompt'], "16:9")
            
            if active_tabs:
                orchestrate_session(active_tabs, active_names, "chars", ui_bridge)
                for _ in active_tabs: bump()
                for t in active_tabs: t.close()

            chunks = [scenes[i:i + 15] for i in range(0, len(scenes), 15)]
            for idx, chunk in enumerate(chunks):
                pending_img, pending_vid = [], []
                for s in chunk:
                    if not any(os.path.exists(os.path.join(PHOTO_PATH, f"{s['scene_id']}{e}")) for e in [".jpg", ".webp", ".png"]) and s['scene_id'] not in state['scenes']:
                        pending_img.append(s)
                    else: bump()
                    if not any(os.path.exists(os.path.join(VIDEO_PATH, f"video_{s['scene_id']}{e}")) for e in [".mp4", ".mov"]) and f"video_{s['scene_id']}" not in state['videos']:
                        pending_vid.append(s)
                    else: bump()

                if not pending_img and not pending_vid: continue
                
                pool = {}
                if pending_img:
                    for s in pending_img:
                        t = ctx.new_page()
                        if runtime_config["stealth_mode"]: stealth_sync(t)
                        pool[s['scene_id']] = t
                        sync_browser_context(t)
                        inject_persistence_layer(t, s['scene_id'])
                        set_workflow_mode(t, "image")
                        ref = os.path.join(PHOTO_PATH, f"{s['char_id']}.jpg")
                        if not os.path.exists(ref): ref = os.path.join(PHOTO_PATH, f"{s['char_id']}.webp")
                        attach_asset(t, ref)
                        jitter(2, 4)
                        dispatch_prompt(t, s['scene_prompt'], "16:9")
                    orchestrate_session(list(pool.values()), list(pool.keys()), "scenes", ui_bridge)
                    for _ in pending_img: bump()

                if pending_vid:
                    v_tabs, v_ids = [], []
                    for s in pending_vid:
                        t = pool.get(s['scene_id'])
                        if not t:
                            t = ctx.new_page()
                            if runtime_config["stealth_mode"]: stealth_sync(t)
                            pool[s['scene_id']] = t
                        v_tabs.append(t); v_ids.append(f"video_{s['scene_id']}")
                        t.bring_to_front()
                        sync_browser_context(t)
                        inject_persistence_layer(t, f"video_{s['scene_id']}")
                        set_workflow_mode(t, "video")
                        frame = os.path.join(PHOTO_PATH, f"{s['scene_id']}.jpg")
                        if not os.path.exists(frame): frame = os.path.join(PHOTO_PATH, f"{s['scene_id']}.webp")
                        attach_asset(t, frame)
                        jitter(3, 5)
                        dispatch_prompt(t, s['motion_prompt'], "16:9")
                    orchestrate_session(v_tabs, v_ids, "videos", ui_bridge)
                    for _ in pending_vid: bump()
                
                for t in pool.values(): t.close()
    except: traceback.print_exc()

if __name__ == "__main__":
    main()
