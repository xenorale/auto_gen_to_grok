
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
        "headless": True,
        "proxy": "" # Added for manual proxy support
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
    debug_port = runtime_config.get("debug_port", 9222)
    if is_port_in_use(debug_port):
        print(f"[CORE] Port {debug_port} is busy. Using existing instance...")
    else:
        print("[CORE] Launching browser...")
        # Clear cache/shader cache to speed up
        user_data = runtime_config.get("user_data_dir", r"C:\chrome_debug_profile")
        try:
            import shutil
            shutil.rmtree(os.path.join(user_data, "Default", "Cache"), ignore_errors=True)
            shutil.rmtree(os.path.join(user_data, "ShaderCache"), ignore_errors=True)
        except: pass

        is_headless = runtime_config.get("headless", True)
        if isinstance(is_headless, str):
            is_headless = is_headless.lower() == 'true'

        headless_args = "--headless --disable-gpu" if is_headless else ""
        base_args = "--no-first-run --no-default-browser-check --disable-dev-shm-usage --mute-audio --disk-cache-size=104857600" # 100MB cache limit
        # Manual proxy support
        proxy_arg = f"--proxy-server=\"{runtime_config['proxy']}\"" if runtime_config.get("proxy") else ""
        
        chrome_exe = runtime_config.get("chrome_path", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        
        cmd = f'"{chrome_exe}" --remote-debugging-port={debug_port} --user-data-dir="{user_data}" {headless_args} {base_args} {proxy_arg} --log-level=3'
        subprocess.Popen(cmd, shell=True)
        time.sleep(5)

def sync_browser_context(page: Page):
    try:
        # Add network logging to diagnose slow loading
        request_starts = {}
        def on_request(request):
            request_starts[request] = time.time()
            
        def on_response(response):
            req = response.request
            if req in request_starts:
                duration = time.time() - request_starts[req]
                if duration > 3.0:  # Log resources taking >3s
                    try:
                        print(f"[NETWORK] Долгий запрос ({duration:.1f} сек): {req.url[:100]}...")
                    except: pass

        page.on("request", on_request)
        page.on("response", on_response)

        start_t = time.time()
        print("[NETWORK] Начало загрузки страницы (https://grok.com/imagine)...")
        
        # Block known trackers to speed up VPN connections
        def block_trackers(route):
            url = route.request.url
            if any(t in url for t in ["google-analytics", "googletagmanager", "sentry", "datadog", "telemetry"]):
                route.abort()
            else:
                route.continue_()
                
        page.route("**/*", block_trackers)

        # Wait a bit longer and use a more reliable wait state
        page.goto("https://grok.com/imagine", wait_until="domcontentloaded", timeout=60000)
        
        end_t = time.time()
        print(f"[NETWORK] Страница загружена за {end_t - start_t:.1f} сек.")
        
        # Give it a moment to settle dynamic elements
        time.sleep(2)
    except Exception as e:
        print(f"[NETWORK] Ошибка/Таймаут загрузки: {e}")

def set_workflow_mode(page: Page, mode: str):
    label = "Видео" if mode == "video" else "Изображение"
    alt = "Video" if mode == "video" else "Image"
    log(f"Setting mode: {mode}", "DEBUG")
    
    try:
        # Убрали долгие таймауты: если поле ввода уже есть, можно вообще не ждать.
        # Даем максимум 1.5 секунды на переключение режима (поиск RU/EN текста одновременно)
        page.locator(f'text="{label}", text="{alt}"').first.click(timeout=1500, force=True)
        time.sleep(0.5)
        return True
    except: 
        pass
        
    return False

def dispatch_prompt(page: Page, content: str, aspect_ratio: str):
    try:
        final_query = re.sub(r"--ar\s+\S+", f"--ar {aspect_ratio}", content) if "--ar" in content else f"{content.strip()} --ar {aspect_ratio}"
        log(f"Sending prompt: {final_query[:50]}...", "DEBUG")
        
        # Robust check for the input area
        area = page.locator('textarea, [contenteditable="true"], [placeholder*="Grok"], [aria-label*="Grok"]').first
        try:
            area.wait_for(state="visible", timeout=25000)
        except Exception as e:
            # Diagnostic: capture what the bot actually sees
            diag_path = f"error_dispatch_{int(time.time())}.png"
            page.screenshot(path=diag_path)
            log(f"Dispatch failed: Input area not found. Diagnostic saved to {diag_path}", "ERROR")
            log(f"Current URL: {page.url}", "DEBUG")
            return False
            
        time.sleep(1) # Extra settle time
        area.click()
        area.fill(final_query)
        time.sleep(1)
        page.keyboard.press("Enter")
        return True
    except Exception as e:
        log(f"Dispatch failed: {str(e)}", "ERROR")
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

def log(msg, level="INFO"):
    t = time.strftime("%H:%M:%S")
    print(f"[{t}] [{level}] {msg}")

def capture_media(page: Page, name: str, category: str, variant_index: int = 0):
    try:
        log(f"Capturing high-res media for {name} (index {variant_index})...", "CORE")
        
        # Wait until the image is likely fully loaded
        time.sleep(2) 
        
        nodes_js = """async () => {
            const results = [];
            const nodes = Array.from(document.querySelectorAll('img, video, div, span')).filter(el => {
                if (el.offsetWidth < 150) return false;
                if (el.tagName === 'IMG') return el.complete && el.naturalWidth > 200;
                const bg = window.getComputedStyle(el).backgroundImage;
                return (el.src || (bg && bg !== 'none'));
            });

            for (const el of nodes) {
                let src = el.src || el.querySelector('source')?.src;
                if (!src) {
                    const bg = window.getComputedStyle(el).backgroundImage;
                    if (bg && bg.startsWith('url(')) src = bg.slice(4, -1).replace(/["']/g, "");
                }
                if (src) results.push({ src, tag: el.tagName });
            }
            return results;
        }"""
        
        payloads = page.evaluate(nodes_js)
        if not payloads:
            log(f"No sharp media found for {name} after wait", "ERROR")
            return False
            
        if variant_index >= len(payloads): variant_index = 0 # Fallback to first if index lost
        
        target = payloads[variant_index]
        is_vid = target.get('tag') == 'VIDEO'
        
        # Aggressive retry for high-res download
        for attempt in range(3):
            download_js = """async (src) => {
                try {
                    const r = await fetch(src);
                    if (!r.ok) return { error: r.status };
                    const b = await r.blob();
                    if (b.size < 10000) return { error: "too_small" }; // Skip tiny images
                    return await new Promise((res) => {
                        const f = new FileReader();
                        f.onloadend = () => res({ b64: f.result.split(',')[1], mime: b.type, size: b.size });
                        f.readAsDataURL(b);
                    });
                } catch (e) { return { error: e.message }; }
            }"""
            data = page.evaluate(download_js, target['src'])
            
            if "error" not in data:
                ext = ".mp4" if is_vid else ".jpg"
                if "webp" in data.get('mime', ''): ext = ".webp"
                dest = VIDEO_PATH if (is_vid or name.startswith("video_")) else PHOTO_PATH
                full_path = os.path.join(dest, f"{name}{ext}")
                
                with open(full_path, "wb") as f:
                    f.write(base64.b64decode(data['b64']))
                
                log(f"Successfully saved sharp image: {name} ({data['size']} bytes)", "CORE")
                commit_progress(category, name)
                return True
                
            log(f"Download attempt {attempt+1} failed for {name}: {data.get('error')}. Retrying...", "DEBUG")
            time.sleep(2)

        return False
    except Exception as e:
        log(f"capture_media exception for {name}: {str(e)}", "ERROR")
    return False

def orchestrate_session(pages, names, category, ui_bridge=None):
    kill_switch = threading.Event()
    commands = []
    
    # CRITICAL: Clear any existing sync flags in the browser tabs from previous runs
    for p in pages:
        try:
            p.evaluate("document.querySelectorAll('[data-synced-to-gui], [data-preview-synced]').forEach(n => { n.removeAttribute('data-synced-to-gui'); n.removeAttribute('data-preview-synced'); })")
        except: pass

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
    
    log(f"Session started for {category}. Waiting for manual selection in GUI...", "CORE")
    
    while not kill_switch.is_set():
        internal_sync(None, None, None)
        
        while commands:
            cmd = commands.pop(0)
            if cmd['name'] in names:
                idx = names.index(cmd['name'])
                p = pages[idx]
                if cmd['action'] == 'save':
                    v_idx = cmd.get('variant_index', 0)
                    log(f"Manual save command received for {cmd['name']} (variant {v_idx})", "CORE")
                    capture_media(p, cmd['name'], category, variant_index=v_idx)
                elif cmd['action'] == 'regen':
                    log(f"Regeneration command received for {cmd['name']}", "CORE")
                    p.bring_to_front()
                    p.keyboard.press("Enter")
                    # Clear flags on regen to allow new images to sync
                    p.evaluate("document.querySelectorAll('[data-synced-to-gui]').forEach(n => n.removeAttribute('data-synced-to-gui'))")

        sync_previews(pages, names, internal_sync)
        time.sleep(1)

def sync_previews(pages, names, callback):
    if not callback: return
    for i, page in enumerate(pages):
        try:
            diag_js = """async () => {
                const results = [];
                const nodes = Array.from(document.querySelectorAll('img, video, [style*="background-image"]'))
                                   .filter(n => n.offsetWidth > 40);
                
                for (const node of nodes) {
                    try {
                        let src = node.src || node.querySelector('source')?.src;
                        if (!src) {
                            const bg = window.getComputedStyle(node).backgroundImage;
                            if (bg && bg.startsWith('url(')) src = bg.slice(4, -1).replace(/["']/g, "");
                        }
                        
                        if (!src || src.includes('data:image/svg+xml')) continue;
                        if (node.hasAttribute('data-synced-to-gui')) continue;

                        const r = await fetch(src);
                        if (!r.ok) continue;
                        const b = await r.blob();
                        if (b.size < 1000) continue;

                        const b64 = await new Promise(res => {
                            const f = new FileReader();
                            f.onloadend = () => res(f.result.split(',')[1]);
                            f.readAsDataURL(b);
                        });
                        
                        node.setAttribute('data-synced-to-gui', 'true');
                        results.push({ b64, is_vid: node.tagName === 'VIDEO' });
                    } catch (e) {}
                }
                return results;
            }"""
            
            variants_data = page.evaluate(diag_js)
            if variants_data and len(variants_data) > 0:
                log(f"Sending {len(variants_data)} images for {names[i]} to GUI", "DEBUG")
                callback(names[i], variants_data, False)
        except Exception as e:
            log(f"sync_previews error for {names[i]}: {str(e)}", "DEBUG")

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

            # Выставляем размер порций в зависимости от формата
            chunk_size = 15 if ar_mode == "16:9" else 999
            
            char_chunks = [chars[i:i + chunk_size] for i in range(0, len(chars), chunk_size)]
            for chunk in char_chunks:
                active_tabs, active_names = [], []
                for c in chunk:
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

            scene_chunks = [scenes[i:i + chunk_size] for i in range(0, len(scenes), chunk_size)]
            for idx, chunk in enumerate(scene_chunks):
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
