from playwright.sync_api import sync_playwright, Page
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

# Настройка путей
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
USER_DATA_DIR = r"C:\chrome_debug_profile"

print("\n" + "="*40)
print("📂 НАСТРОЙКА РАБОЧЕЙ ПАПКИ")
BASE_DIR = input("Введите путь к папке проекта (или Enter для текущей): ").strip()
if not BASE_DIR: BASE_DIR = os.getcwd()

PHOTO_PATH = os.path.join(BASE_DIR, "photo")
VIDEO_PATH = os.path.join(BASE_DIR, "video")
MUSIC_PATH = os.path.join(BASE_DIR, "music")

# Пути к CSV внутри проекта
CHARS_CSV = os.path.join(BASE_DIR, "characters.csv")
SCENES_CSV = os.path.join(BASE_DIR, "scenes.csv")

# Проверка наличия CSV
if not os.path.exists(CHARS_CSV) or not os.path.exists(SCENES_CSV):
    print(f"\n❌ ОШИБКА: Файлы characters.csv или scenes.csv не найдены в {BASE_DIR}")
    print("Пожалуйста, скопируйте их в указанную папку и запустите бота снова.")
    sys.exit(1)

print("🎬 ВЫБОР РЕЖИМА ВИДЕО:")
print("1. Короткое (Short) - Формат 9:16 (вертикальное)")
print("2. Длинное (Long) - Формат 16:9 (горизонтальное) + Пакетная обработка по 15 сцен")
mode_choice = input("Выберите вариант (1 или 2): ").strip()

IS_LONG_MODE = mode_choice == "2"
TARGET_AR = "16:9" if IS_LONG_MODE else "9:16"
BATCH_SIZE = 15 if IS_LONG_MODE else 100

PROGRESS_FILE = os.path.join(BASE_DIR, "progress.json")

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r") as f:
            try: return json.load(f)
            except: pass
    return {"chars": [], "scenes": [], "videos": []}

def save_progress(category, item_id):
    prog = load_progress()
    if item_id not in prog[category]:
        prog[category].append(item_id)
        with open(PROGRESS_FILE, "w") as f:
            json.dump(prog, f, indent=4)

def human_delay(min_sec=2, max_sec=5):
    time.sleep(random.uniform(min_sec, max_sec))

for p in [PHOTO_PATH, VIDEO_PATH, MUSIC_PATH]:
    if not os.path.exists(p): os.makedirs(p)
print(f"✅ Проект загружен. Режим: {'Длинное (16:9)' if IS_LONG_MODE else 'Короткое (9:16)'}")
print("="*40 + "\n")

if sys.platform == "win32":
    try: sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        import codecs
        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())

def check_for_save_requests(pages, filenames, category):
    for i, page in enumerate(pages):
        process_save_for_page(page, filenames[i], category)

def process_save_for_page(page, name, category):
    try:
        target = page.locator("#bot-active-media")
        if target.count() > 0:
            # Получаем параметры медиа-элемента
            result = page.evaluate("""async () => {
                const el = document.getElementById('bot-active-media');
                if (!el) return { error: 'Not found' };
                const tag = el.tagName;
                
                if (tag === 'VIDEO' && el.readyState < 2) {
                    await new Promise(r => {
                        el.addEventListener('loadeddata', r, { once: true });
                        setTimeout(r, 3000); 
                    });
                }

                let src = el.src || '';
                if (tag === 'VIDEO' && (!src || src.startsWith('blob:'))) {
                    const source = el.querySelector('source');
                    if (source) src = source.src || src;
                }
                
                if (!src) return { error: 'No src found', tagName: tag };
                
                try {
                    const resp = await fetch(src);
                    if (resp.ok) {
                        const blob = await resp.blob();
                        const b64 = await new Promise((res) => {
                            const reader = new FileReader();
                            reader.onloadend = () => res(reader.result.split(',')[1]);
                            reader.readAsDataURL(blob);
                        });
                        return { b64, type: blob.type, tagName: tag, src: src };
                    }
                    return { error: 'Status ' + resp.status, tagName: tag, src: src };
                } catch (e) { 
                    return { error: e.message, tagName: tag, src: src }; 
                }
            }""")
            
            tagName = result.get('tagName', 'IMG')
            is_video = (tagName == "VIDEO")
            ext = ".mp4" if is_video else ".jpg"
            if result.get('type') == "image/webp": ext = ".webp"
            
            # Определяем папку сохранения
            target_dir = VIDEO_PATH if (is_video or name.startswith("video_")) else PHOTO_PATH
            save_path = os.path.join(target_dir, f"{name}{ext}")
            success = False

            # Метод 1: Base64
            if result.get('b64') and len(result['b64']) > 1000:
                with open(save_path, "wb") as f:
                    f.write(base64.b64decode(result['b64']))
                print(f"  ✅ СОХРАНЕНО: {os.path.basename(save_path)}")
                success = True
            
            # Метод 2: Network Request (403 bypass)
            elif not success:
                src = result.get('src')
                if src and src.startswith('http'):
                    try:
                        response = page.context.request.get(src)
                        if response.ok:
                            ct = response.headers.get("content-type", "").lower()
                            if "video" in ct: ext = ".mp4"
                            elif "webp" in ct: ext = ".webp"
                            else: ext = ".jpg"
                            
                            target_dir = VIDEO_PATH if "video" in ct else PHOTO_PATH
                            save_path = os.path.join(target_dir, f"{name}{ext}")
                            
                            with open(save_path, "wb") as f:
                                f.write(response.body())
                            print(f"  ✅ СОХРАНЕНО: {os.path.basename(save_path)}")
                            success = True
                    except: pass

            # Метод 3: Скриншот
            if not success and tagName == "IMG":
                try:
                    box = target.bounding_box()
                    if box:
                        page.evaluate("""() => {
                            const style = document.createElement('style');
                            style.id = 'bot-temp-style';
                            style.innerHTML = 'button, [role="button"], [class*="Video"], [class*="overlay"] { visibility: hidden !important; } #bot-save-btn { visibility: visible !important; }';
                            document.head.appendChild(style);
                        }""")
                        time.sleep(0.5)
                        page.screenshot(path=save_path, clip={
                            "x": box["x"] + 4,
                            "y": box["y"] + 4,
                            "width": box["width"] - 8,
                            "height": box["height"] - 8
                        }, type="jpeg", quality=100)
                        page.evaluate("if(document.getElementById('bot-temp-style')) document.getElementById('bot-temp-style').remove()")
                        print(f"  ✅ СОХРАНЕНО (С кропом 4px): {os.path.basename(save_path)}")
                        success = True
                except Exception as e:
                    print(f"  ❌ Ошибка скриншота: {e}")

            finalize_save(page, success, category, name)
            return success
    except: pass
    return False

def poll_gui_commands(pages, filenames, category, preview_callback):
    if not preview_callback: return []
    # Вызываем колбэк с пустыми данными, чтобы он вернул команду из очереди, если она есть
    cmd = preview_callback(None, None, None)
    return [cmd] if cmd else []

def wait_for_user_enter(pages, filenames, category, preview_callback=None):
    stop_flag = threading.Event()
    gui_commands = []
    
    def internal_preview_callback(name, data, is_video):
        if preview_callback:
            # Если переданы данные - это новое превью
            if name is not None:
                cmd = preview_callback(name, data, is_video)
                if cmd: gui_commands.append(cmd)
            # Если name is None - это просто опрос очереди команд
            else:
                cmd = preview_callback(None, None, None)
                if cmd: gui_commands.append(cmd)

    def input_thread():
        input()
        stop_flag.set()
    
    thread = threading.Thread(target=input_thread, daemon=True)
    thread.start()
    print("\n" + "="*60 + "\n🚀 ОЖИДАНИЕ СОХРАНЕНИЯ. Когда закончишь, НАЖМИ ENTER ЗДЕСЬ.\n" + "="*60)
    
    while not stop_flag.is_set():
        # Опрашиваем GUI на наличие команд (даже если нет новых превью)
        internal_preview_callback(None, None, None)
        
        # Обработка команд
        while gui_commands:
            cmd = gui_commands.pop(0)
            target_name = cmd.get('name')
            action = cmd.get('action')
            
            if target_name in filenames:
                idx = filenames.index(target_name)
                page = pages[idx]
                
                if action == 'save':
                    print(f"  📥 GUI: SAVE -> {target_name}")
                    page.evaluate("""() => {
                        const media = Array.from(document.querySelectorAll('img, video')).filter(el => el.offsetWidth > 200);
                        if (media.length > 0) {
                            const target = media.sort((a, b) => {
                                if (a.tagName === 'VIDEO' && b.tagName !== 'VIDEO') return -1;
                                if (a.tagName !== 'VIDEO' && b.tagName === 'VIDEO') return 1;
                                return (b.offsetWidth * b.offsetHeight) - (a.offsetWidth * a.offsetHeight);
                            })[0];
                            document.querySelectorAll('#bot-active-media').forEach(el => el.id = '');
                            target.id = 'bot-active-media';
                        }
                    }""")
                    process_save_for_page(page, target_name, category)
                
                elif action == 'regen':
                    print(f"  ♻️ GUI: REGEN -> {target_name}")
                    # Фокусируемся и нажимаем Enter
                    page.bring_to_front()
                    page.keyboard.press("Enter")
                    page.evaluate("document.querySelectorAll('[data-preview-sent]').forEach(el => el.removeAttribute('data-preview-sent'))")

        check_for_save_requests(pages, filenames, category)
        check_for_previews(pages, filenames, internal_preview_callback)
        time.sleep(0.5)

def switch_mode(page: Page, mode: str):
    target = "Видео" if mode == "video" else "Изображение"
    alt = "Video" if mode == "video" else "Image"
    print(f"  🔄 Переключение в режим {mode} ('{target}')...")
    time.sleep(2)
    try:
        selector = f'xpath=//button[text()="{target}" or text()="{alt}"] | //div[@role="button"][text()="{target}" or text()="{alt}"] | //span[text()="{target}" or text()="{alt}"]'
        btn = page.locator(selector).first
        if btn.is_visible(timeout=5000):
            btn.click()
            time.sleep(1.5)
            print(f"    ✅ Режим '{target}' выбран")
            return True
        for label in [target, alt]:
            btn = page.get_by_text(label, exact=True).first
            if btn.is_visible(timeout=2000):
                btn.click()
                time.sleep(1.5)
                print(f"    ✅ Режим '{label}' выбран (точно)")
                return True
    except: pass
    print(f"  ⚠️ Предупреждение: Не удалось найти точную кнопку {target}")
    return False

def send_prompt(page: Page, prompt: str, ar: str = "9:16"):
    try:
        if "--ar" in prompt:
            prompt = re.sub(r"--ar\s+\S+", f"--ar {ar}", prompt)
        else:
            prompt = prompt.strip() + f" --ar {ar}"
            
        box = page.locator('textarea, [contenteditable="true"]').first
        box.wait_for(state="visible", timeout=15000)
        box.click()
        box.fill(prompt)
        time.sleep(1) 
        page.keyboard.press("Enter")
        print(f"  🚀 Промпт ({ar}) отправлен")
        return True
    except: return False

def ensure_chrome():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(('localhost', 9222)) == 0: return True
    subprocess.Popen(f'"{CHROME_PATH}" --remote-debugging-port=9222 --user-data-dir="{USER_DATA_DIR}"', shell=True)
    time.sleep(5)
    return True

def inject_ui_logic(page: Page, target_name: str):
    js = f"""
    (() => {{
        const inject = () => {{
            if (!document.body) return;
            let btn = document.getElementById('bot-save-btn');
            const expectedText = '📸 СОХРАНИТЬ {target_name}';
            if (btn) {{
                if (btn.getAttribute('data-target') !== '{target_name}') {{
                    btn.setAttribute('data-target', '{target_name}');
                    btn.setAttribute('data-orig-text', expectedText);
                    if (!btn.innerText.includes('⏳') && !btn.innerText.includes('✅')) {{
                        btn.innerText = expectedText;
                    }}
                }}
                return;
            }}
            btn = document.createElement('button');
            btn.id = 'bot-save-btn';
            btn.setAttribute('data-target', '{target_name}');
            btn.setAttribute('data-orig-text', expectedText);
            btn.innerText = expectedText;
            btn.style = 'position:fixed; bottom:20px; left:20px; z-index:9999999; background:#ffcc00; color:black; padding:15px 25px; border:3px solid black; font-weight:bold; cursor:pointer; border-radius:10px; box-shadow: 5px 5px 0px black; font-family: sans-serif; font-size: 14px;';
            btn.onclick = (e) => {{
                e.preventDefault();
                e.stopPropagation();
                const media = Array.from(document.querySelectorAll('img, video')).filter(el => el.offsetWidth > 200);
                if (media.length === 0) {{ alert("Медиа не найдено!"); return; }}
                const target = media.sort((a, b) => {{
                    if (a.tagName === 'VIDEO' && b.tagName !== 'VIDEO') return -1;
                    if (a.tagName !== 'VIDEO' && b.tagName === 'VIDEO') return 1;
                    return (b.offsetWidth * b.offsetHeight) - (a.offsetWidth * a.offsetHeight);
                }})[0];
                document.querySelectorAll('#bot-active-media').forEach(el => el.id = '');
                target.id = 'bot-active-media';
                btn.innerText = '⏳ СОХРАНЯЮ...';
            }};
            document.body.appendChild(btn);
        }};
        if (window._botInterval) clearInterval(window._botInterval);
        window._botInterval = setInterval(inject, 1000);
        if (window._botObserver) window._botObserver.disconnect();
        window._botObserver = new MutationObserver(inject);
        window._botObserver.observe(document.documentElement, {{ childList: true, subtree: true }});
        inject();
    }})();
    """
    page.add_init_script(js)
    try: 
        page.wait_for_selector("body", timeout=10000)
        page.evaluate(js)
    except: pass

def safe_goto(page: Page, url: str):
    try: page.goto(url, wait_until="commit", timeout=45000)
    except: pass

def finalize_save(page, success, category=None, item_id=None):
    try:
        if success and category and item_id:
            save_progress(category, item_id)
        page.evaluate(f"""() => {{
            const el = document.getElementById('bot-active-media');
            if (el) el.id = 'bot-saved';
            const btn = document.getElementById('bot-save-btn');
            if (btn) {{
                btn.style.background = '{"#00ff00" if success else "#ff0000"}';
                btn.innerText = '{"✅ ГОТОВО!" if success else "❌ ОШИБКА"}';
                setTimeout(() => {{ 
                    btn.style.background = '#ffcc00'; 
                    btn.innerText = btn.getAttribute('data-orig-text') || '📸 СОХРАНИТЬ'; 
                }}, 2000);
            }}
        }}""")
    except: pass

def upload_file(page: Page, file_path: str):
    if not os.path.exists(file_path):
        print(f"  ❌ ФАЙЛ НЕ НАЙДЕН: {file_path}")
        return False
    try:
        page.wait_for_selector('input[type="file"], [role="button"]', timeout=5000)
        inp = page.locator('input[type="file"]')
        if inp.count() > 0:
            inp.first.set_input_files(file_path)
            return True
        page.get_by_role("button", name=re.compile(r"upload|attach|file|image", re.IGNORECASE)).first.click()
        page.wait_for_selector('input[type="file"]', timeout=3000)
        page.locator('input[type="file"]').first.set_input_files(file_path)
        return True
    except:
        try:
            page.set_input_files('input[type="file"]', file_path)
            return True
        except: return False

import json
from playwright_stealth import stealth_async, stealth_sync

# Загрузка конфига
CONFIG_FILE = "config.json"
def load_config():
    default = {
        "chrome_path": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "user_data_dir": r"C:\chrome_debug_profile",
        "debug_port": 9222,
        "stealth_mode": True
    }
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return {**default, **json.load(f)}
    return default

CONFIG = load_config()
CHROME_PATH = CONFIG["chrome_path"]
USER_DATA_DIR = CONFIG["user_data_dir"]

# ... (остальной импорт и настройки путей без изменений до main)

def main(update_progress_fn=None, preview_callback=None):
    try:
        ensure_chrome()
        progress = load_progress()
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://localhost:{CONFIG['debug_port']}")
            context = browser.contexts[0]
            
            chars = list(csv.DictReader(open(CHARS_CSV, encoding='utf-8')))
            scenes = list(csv.DictReader(open(SCENES_CSV, encoding='utf-8')))

            total_tasks = len(chars) + len(scenes) * 2 # Фото + Видео
            current_task_count = 0

            def update_progress():
                nonlocal current_task_count
                current_task_count += 1
                if update_progress_fn:
                    update_progress_fn(current_task_count / total_tasks)

            print("\n=== ЭТАП 1: ПЕРСОНАЖИ ===")
            char_tabs = []
            char_names = []
            for char in chars:
                # SMART SKIP: Проверка наличия файла
                exists = any(os.path.exists(os.path.join(PHOTO_PATH, f"{char['char_id']}{ext}")) for ext in [".jpg", ".webp", ".png"])
                if exists or char['char_id'] in progress['chars']:
                    print(f"⏩ {char['char_id']} уже готов (файл найден), пропускаем.")
                    update_progress()
                    continue
                
                tab = context.new_page()
                if CONFIG["stealth_mode"]:
                    stealth_sync(tab)
                
                char_tabs.append(tab)
                char_names.append(char['char_id'])
                safe_goto(tab, "https://grok.com/imagine")
                inject_ui_logic(tab, char['char_id'])
                print(f"👤 {char['char_id']}:")
                switch_mode(tab, "image")
                human_delay(1, 2)
                send_prompt(tab, char['char_prompt'], TARGET_AR)
            
            if char_tabs:
                wait_for_user_enter(char_tabs, char_names, "chars", preview_callback)
                for _ in char_tabs: update_progress()
                for t in char_tabs: t.close()

            scene_chunks = [scenes[i:i + BATCH_SIZE] for i in range(0, len(scenes), BATCH_SIZE)]
            for chunk_idx, chunk in enumerate(scene_chunks):
                # SMART SKIP для сцен
                chunk_for_scenes = []
                for s in chunk:
                    exists = any(os.path.exists(os.path.join(PHOTO_PATH, f"{s['scene_id']}{ext}")) for ext in [".jpg", ".webp", ".png"])
                    if not exists and s['scene_id'] not in progress['scenes']:
                        chunk_for_scenes.append(s)
                    else:
                        print(f"⏩ Сцена {s['scene_id']} уже готова, пропускаем фото.")
                        update_progress()

                chunk_for_videos = []
                for s in chunk:
                    exists = any(os.path.exists(os.path.join(VIDEO_PATH, f"video_{s['scene_id']}{ext}")) for ext in [".mp4", ".mov"])
                    if not exists and f"video_{s['scene_id']}" not in progress['videos']:
                        chunk_for_videos.append(s)
                    else:
                        print(f"⏩ Сцена {s['scene_id']} уже готова, пропускаем видео.")
                        update_progress()

                if not chunk_for_scenes and not chunk_for_videos:
                    print(f"⏩ Пакет {chunk_idx + 1} полностью готов, пропускаем.")
                    continue

                print(f"\n📦 ОБРАБОТКА ПАКЕТА {chunk_idx + 1} ИЗ {len(scene_chunks)}")
                current_tabs = {}
                
                if chunk_for_scenes:
                    print(f"--- ПАКЕТ {chunk_idx + 1}: Генерация изображений ---")
                    for scene in chunk_for_scenes:
                        tab = context.new_page()
                        if CONFIG["stealth_mode"]: stealth_sync(tab)
                        current_tabs[scene['scene_id']] = tab
                        safe_goto(tab, "https://grok.com/imagine")
                        inject_ui_logic(tab, scene['scene_id'])
                        print(f"🎬 Сцена {scene['scene_id']}:")
                        switch_mode(tab, "image")
                        ref = os.path.join(PHOTO_PATH, f"{scene['char_id']}.jpg")
                        if not os.path.exists(ref): ref = os.path.join(PHOTO_PATH, f"{scene['char_id']}.webp")
                        upload_file(tab, ref)
                        human_delay(2, 4)
                        send_prompt(tab, scene['scene_prompt'], TARGET_AR)
                    wait_for_user_enter(list(current_tabs.values()), list(current_tabs.keys()), "scenes", preview_callback)
                    for _ in chunk_for_scenes: update_progress()

                if chunk_for_videos:
                    print(f"--- ПАКЕТ {chunk_idx + 1}: Анимация ---")
                    v_tabs, v_ids = [], []
                    for scene in chunk_for_videos:
                        tab = current_tabs.get(scene['scene_id'])
                        if not tab: 
                            tab = context.new_page()
                            if CONFIG["stealth_mode"]: stealth_sync(tab)
                            current_tabs[scene['scene_id']] = tab
                        v_tabs.append(tab); v_ids.append(f"video_{scene['scene_id']}")
                        tab.bring_to_front()
                        safe_goto(tab, "https://grok.com/imagine")
                        inject_ui_logic(tab, f"video_{scene['scene_id']}")
                        print(f"🎥 Видео {scene['scene_id']}:")
                        switch_mode(tab, "video")
                        frame = os.path.join(PHOTO_PATH, f"{scene['scene_id']}.jpg")
                        if not os.path.exists(frame): frame = os.path.join(PHOTO_PATH, f"{scene['scene_id']}.webp")
                        upload_file(tab, frame)
                        human_delay(3, 5)
                        send_prompt(tab, scene['motion_prompt'], TARGET_AR)
                    wait_for_user_enter(v_tabs, v_ids, "videos", preview_callback)
                    for _ in chunk_for_videos: update_progress()
                
                for t in current_tabs.values(): t.close()

            print("\n✅ ВСЁ ГОТОВО!")
    except Exception: traceback.print_exc()


if __name__ == "__main__":
    main()
