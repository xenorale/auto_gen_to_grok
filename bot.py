
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
from playwright_stealth import Stealth

CONFIG_FILE = "config.json"

def load_config():
    defaults = {
        "chrome_path": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "user_data_dir": r"C:\chrome_debug_profile",
        "debug_port": 9222,
        "stealth_mode": True,
        "headless": True
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                # Ensure boolean conversion if it's a string from some source
                if "headless" in data and isinstance(data["headless"], str):
                    data["headless"] = data["headless"].lower() == "true"
                return {**defaults, **data}
        except: pass
    return defaults

runtime_config = load_config()

# Global paths, to be updated in main()
BASE_DIR = os.getcwd()
PHOTO_PATH = os.path.join(BASE_DIR, "photo")
VIDEO_PATH = os.path.join(BASE_DIR, "video")
MUSIC_PATH = os.path.join(BASE_DIR, "music")
CHARS_CSV = os.path.join(BASE_DIR, "characters.csv")
SCENES_CSV = os.path.join(BASE_DIR, "scenes.csv")
PROGRESS_FILE = os.path.join(BASE_DIR, "progress.json")

def _init_folders():
    for d in [PHOTO_PATH, VIDEO_PATH, MUSIC_PATH]:
        if not os.path.exists(d): 
            try:
                os.makedirs(d, exist_ok=True)
                print(f"[CORE] Created directory: {d}")
            except Exception as e:
                print(f"[ERROR] Failed to create {d}: {e}")

# Initial run for default path
_init_folders()

def apply_stealth(page):
    if runtime_config["stealth_mode"]:
        stealth_obj = Stealth()
        stealth_obj.apply_stealth_sync(page)

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

def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def bridge_connection():
    # Only attempt to reset if the port is actually in use
    debug_port = runtime_config.get("debug_port", 9222)
    if is_port_in_use(debug_port):
        print(f"[CORE] Port {debug_port} is busy. Checking connection...")
        try:
            # We try to connect to see if it's already our Chrome or something else
            # But for simplicity and safety, if it's busy, we'll just try to use it
            # instead of blindly killing. 
            # However, if the user wants it to be 'background', we should ensure 
            # the instance we want is the one running.
            pass 
        except: pass
    else:
        print("[CORE] Launching background browser...")
        # Most reliable combination of flags for headless mode in Chrome
        is_headless = runtime_config.get("headless", True)
        if isinstance(is_headless, str):
            is_headless = is_headless.lower() == 'true'
            
        headless_args = "--headless --disable-gpu --window-size=1920,1080" if is_headless else ""
        silent_args = "--log-level=3 --silent --disable-logging"
        user_data = runtime_config.get("user_data_dir", r"C:\chrome_debug_profile")
        chrome_exe = runtime_config.get("chrome_path", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        
        debug_port = runtime_config.get("debug_port", 9222)
        cmd = f'"{chrome_exe}" --remote-debugging-port={debug_port} --user-data-dir="{user_data}" {headless_args} {silent_args}'
        subprocess.Popen(cmd, shell=True)
        time.sleep(3)
    return True

def sync_browser_context(page: Page):
    try:
        page.goto("https://grok.com/imagine", wait_until="commit", timeout=30000)
    except: pass

def set_workflow_mode(page: Page, mode: str):
    label = "Видео" if mode == "video" else "Изображение"
    alt = "Video" if mode == "video" else "Image"
    print(f"[DEBUG] Setting mode: {mode}")
    try:
        # Wait for Grok to load enough to show mode buttons
        page.wait_for_selector(f"text={label}", timeout=10000)
    except:
        try:
            page.wait_for_selector(f"text={alt}", timeout=5000)
        except: pass

    try:
        selectors = [
            f'xpath=//button[contains(., "{label}") or contains(., "{alt}")]',
            f'xpath=//div[@role="button"][contains(., "{label}") or contains(., "{alt}")]',
            f'xpath=//span[contains(text(), "{label}") or contains(text(), "{alt}")]',
            f'text="{label}"',
            f'text="{alt}"'
        ]
        for sel in selectors:
            target = page.locator(sel).first
            if target.is_visible(timeout=2000):
                # Verify if it is already selected by checking parent or class (optional)
                target.click(force=True)
                time.sleep(1.5)
                return True
    except: pass
    return False

def dispatch_prompt(page: Page, content: str, aspect_ratio: str):
    try:
        final_query = re.sub(r"--ar\s+\S+", f"--ar {aspect_ratio}", content) if "--ar" in content else f"{content.strip()} --ar {aspect_ratio}"
        print(f"[DEBUG] Sending prompt: {final_query[:50]}...")
        area = page.locator('textarea, [contenteditable="true"], [placeholder*="Grok"]').first
        area.wait_for(state="visible", timeout=15000)
        area.click()
        area.fill(final_query)
        time.sleep(1)
        page.keyboard.press("Enter")
        return True
    except Exception as e:
        print(f"[ERROR] Dispatch failed: {str(e)}")
        return False

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

def capture_media(page: Page, name: str, category: str, variant_index: int = 0):
    try:
        # We look for all potential media nodes
        nodes_js = """() => {
            return Array.from(document.querySelectorAll('img, video')).filter(n => n.offsetWidth > 200).map(el => {
                const tag = el.tagName;
                let src = el.src || '';
                if (tag === 'VIDEO' && (!src || src.startsWith('blob:'))) {
                    const s = el.querySelector('source');
                    if (s) src = s.src || s;
                }
                return { src, tag };
            });
        }"""
        payloads = page.evaluate(nodes_js)
        if not payloads or variant_index >= len(payloads): return False
        
        target = payloads[variant_index]
        is_vid = target.get('tag') == 'VIDEO'
        
        # Download logic
        download_js = """async (src) => {
            const r = await fetch(src);
            const b = await r.blob();
            return await new Promise(res => {
                const f = new FileReader();
                f.onloadend = () => res({ b64: f.result.split(',')[1], mime: b.type });
                f.readAsDataURL(b);
            });
        }"""
        data = page.evaluate(download_js, target['src'])
        
        ext = ".mp4" if is_vid else ".jpg"
        if "webp" in data.get('mime', ''): ext = ".webp"
        
        dest = VIDEO_PATH if (is_vid or name.startswith("video_")) else PHOTO_PATH
        full_path = os.path.join(dest, f"{name}{ext}")
        
        with open(full_path, "wb") as f:
            f.write(base64.b64decode(data['b64']))
            
        commit_progress(category, name)
        return True
    except: pass
    return False

def sync_previews(pages, names, callback):
    if not callback: return
    for i, page in enumerate(pages):
        try:
            # Detect all variants on page
            variants_data = page.evaluate("""async () => {
                const nodes = Array.from(document.querySelectorAll('img, video')).filter(n => 
                    n.offsetWidth > 200
                );
                if (nodes.length === 0) return null;
                
                const results = [];
                for (const node of nodes) {
                    try {
                        const src = node.src || node.querySelector('source')?.src;
                        if (!src) continue;
                        const r = await fetch(src);
                        const b = await r.blob();
                        const b64 = await new Promise(res => {
                            const f = new FileReader();
                            f.onloadend = () => res(f.result.split(',')[1]);
                            f.readAsDataURL(b);
                        });
                        results.push({ b64, is_vid: node.tagName === 'VIDEO' });
                    } catch {}
                }
                return results.slice(0, 4);
            }""")
            
            # Use a marker to only send NEW sets of variants
            current_count = page.evaluate("document.querySelectorAll('[data-preview-synced]').length")
            if variants_data and len(variants_data) > current_count:
                print(f"[DEBUG] Syncing {len(variants_data)} variants to UI for {names[i]}")
                page.evaluate("document.querySelectorAll('img, video').forEach(n => n.setAttribute('data-preview-synced', 'true'))")
                callback(names[i], variants_data, False)
        except Exception as e:
            print(f"[DEBUG] sync_previews error for {names[i]}: {str(e)}")

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
        try: input()
        except: pass
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
                    # cmd now should contain 'variant_index'
                    v_idx = cmd.get('variant_index', 0)
                    capture_media(p, cmd['name'], category, variant_index=v_idx)
                elif cmd['action'] == 'regen':
                    p.bring_to_front()
                    p.keyboard.press("Enter")
                    p.evaluate("document.querySelectorAll('[data-preview-synced]').forEach(n => n.removeAttribute('data-preview-synced'))")

        sync_previews(pages, names, internal_sync)
        time.sleep(0.5)

def main(progress_callback=None, ui_bridge=None, base_dir=None, ar_mode="16:9"):
    try:
        if base_dir:
            global BASE_DIR, PHOTO_PATH, VIDEO_PATH, MUSIC_PATH, CHARS_CSV, SCENES_CSV, PROGRESS_FILE
            BASE_DIR = base_dir
            PHOTO_PATH = os.path.join(BASE_DIR, "photo")
            VIDEO_PATH = os.path.join(BASE_DIR, "video")
            MUSIC_PATH = os.path.join(BASE_DIR, "music")
            CHARS_CSV = os.path.join(BASE_DIR, "characters.csv")
            SCENES_CSV = os.path.join(BASE_DIR, "scenes.csv")
            PROGRESS_FILE = os.path.join(BASE_DIR, "progress.json")
            _init_folders()

        bridge_connection()
        state = get_progress()
        with sync_playwright() as pw:
            session = pw.chromium.connect_over_cdp(f"http://localhost:9222")
            ctx = session.contexts[0]
            
            if not os.path.exists(CHARS_CSV):
                print(f"[ERROR] {CHARS_CSV} not found!")
                return

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
                apply_stealth(t)
                active_tabs.append(t); active_names.append(c['char_id'])
                sync_browser_context(t)
                inject_persistence_layer(t, c['char_id'])
                set_workflow_mode(t, "image")
                jitter(1, 2)
                dispatch_prompt(t, c['char_prompt'], ar_mode)
            
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
                        apply_stealth(t)
                        pool[s['scene_id']] = t
                        sync_browser_context(t)
                        inject_persistence_layer(t, s['scene_id'])
                        set_workflow_mode(t, "image")
                        ref = os.path.join(PHOTO_PATH, f"{s['char_id']}.jpg")
                        if not os.path.exists(ref): ref = os.path.join(PHOTO_PATH, f"{s['char_id']}.webp")
                        attach_asset(t, ref)
                        jitter(2, 4)
                        dispatch_prompt(t, s['scene_prompt'], ar_mode)
                    orchestrate_session(list(pool.values()), list(pool.keys()), "scenes", ui_bridge)
                    for _ in pending_img: bump()

                if pending_vid:
                    v_tabs, v_ids = [], []
                    for s in pending_vid:
                        t = pool.get(s['scene_id'])
                        if not t:
                            t = ctx.new_page()
                            apply_stealth(t)
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
                        dispatch_prompt(t, s['motion_prompt'], ar_mode)
                    orchestrate_session(v_tabs, v_ids, "videos", ui_bridge)
                    for _ in pending_vid: bump()
                
                for t in pool.values(): t.close()
    except: traceback.print_exc()

if __name__ == "__main__":
    main()
