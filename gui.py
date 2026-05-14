import flet as ft
import threading
import sys
import os
import builtins
import importlib
import time
import tempfile
import base64

ACCENT_COLOR = "#007AFF"
GLASS_BG = ft.colors.with_opacity(0.4, "#1F1F1F")
GLASS_BORDER = ft.colors.with_opacity(0.2, "#FFFFFF")

class LogBridge:
    def __init__(self, sink): self.sink = sink
    def write(self, buf):
        if isinstance(buf, bytes):
            buf = buf.decode('utf-8', errors='replace')
        val = buf.strip()
        if val: self.sink(val)
    def flush(self): pass
    def reconfigure(self, **kwargs): pass
    def detach(self): return self

class StudioApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.nexus = threading.Event()
        self.active = False
        self.ar_mode = "16:9"
        self.pending_tasks = []
        self.completed = set()
        self.temp_dir = os.path.join(tempfile.gettempdir(), "auto_grok_previews")
        if not os.path.exists(self.temp_dir):
            os.makedirs(self.temp_dir, exist_ok=True)
        
        self.log_content = ""
        self._build_interface()

    def _build_interface(self):
        self.page.title = "Auto Grok Studio"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.window.width = 1100
        self.page.window.height = 950
        self.page.window.center()
        self.page.padding = 0
        self.page.bgcolor = ft.colors.BLACK

        self.title = ft.Text("Auto Grok Studio", size=32, weight=ft.FontWeight.W_200, color=ft.colors.WHITE)   
        self.indicator = ft.Container(width=10, height=10, border_radius=5, bgcolor=ft.colors.GREY_700)        
        self.status = ft.Text("Готов", size=14, color=ft.colors.GREY_400)

        self.path_field = ft.TextField(
            label="Путь к проекту",
            hint_text="Где лежат CSV файлы...",
            expand=True,
            border_radius=15,
            border_color=GLASS_BORDER,
            bgcolor=ft.colors.with_opacity(0.1, ft.colors.WHITE),
            text_size=14
        )
        
        self.picker = ft.FilePicker(on_result=self._on_path_selection)
        self.page.overlay.append(self.picker)

        self.ar_selector = ft.SegmentedButton(
            segments=[
                ft.Segment(value="16:9", label=ft.Text("16:9 (Кино)")),
                ft.Segment(value="9:16", label=ft.Text("9:16 (Reels)")),
            ],
            selected={"16:9"},
            on_change=self._on_ar_switch,
            show_selected_icon=False
        )

        # Tabs Content
        self.gallery_chars = ft.Row(spacing=10, scroll=ft.ScrollMode.ALWAYS)
        self.gallery_images = ft.Row(spacing=10, scroll=ft.ScrollMode.ALWAYS)
        self.gallery_videos = ft.Row(spacing=10, scroll=ft.ScrollMode.ALWAYS)

        self.log_field = ft.TextField(
            multiline=True,
            read_only=True,
            expand=True,
            text_size=12,
            text_style=ft.TextStyle(font_family="Consolas"),
            bgcolor=ft.colors.BLACK,
            border_color=GLASS_BORDER,
            cursor_color=ACCENT_COLOR
        )

        self.tabs = ft.Tabs(
            selected_index=0,
            animation_duration=300,
            tabs=[
                ft.Tab(
                    text="Генерация",
                    icon=ft.icons.IMAGE_SEARCH_ROUNDED,
                    content=ft.Column([
                        self._section_label("ПЕРСОНАЖИ"),
                        self._wrap_glass(self.gallery_chars, height=260),
                        self._section_label("СЦЕНЫ (ИЗОБРАЖЕНИЯ)"),
                        self._wrap_glass(self.gallery_images, height=260),
                        self._section_label("ВИДЕО"),
                        self._wrap_glass(self.gallery_videos, height=260),
                    ], scroll=ft.ScrollMode.ALWAYS)
                ),
                ft.Tab(
                    text="Логи",
                    icon=ft.icons.TERMINAL_ROUNDED,
                    content=ft.Container(
                        content=ft.Column([
                            ft.Row([
                                ft.Text("Системный лог", weight=ft.FontWeight.BOLD),
                                ft.IconButton(ft.icons.COPY_ROUNDED, on_click=lambda _: self.page.set_clipboard(self.log_field.value))
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            self.log_field
                        ]),
                        padding=20
                    )
                ),
            ],
            expand=True
        )

        self.run_btn = ft.ElevatedButton(
            content=ft.Text("Запустить сессию", size=16, weight=ft.FontWeight.BOLD),
            style=ft.ButtonStyle(
                color=ft.colors.WHITE,
                bgcolor=ACCENT_COLOR,
                padding=ft.padding.symmetric(horizontal=40, vertical=20),
                shape=ft.RoundedRectangleBorder(radius=15),
            ),
            on_click=lambda _: self._launch_engine()
        )

        self.next_btn = ft.IconButton(
            icon=ft.icons.ARROW_FORWARD_IOS_ROUNDED,
            icon_color=ft.colors.WHITE,
            bgcolor=ft.colors.with_opacity(0.2, ft.colors.WHITE),
            on_click=lambda _: self.nexus.set()
        )

        self.page.add(
            ft.Container(
                expand=True,
                gradient=ft.LinearGradient(
                    begin=ft.alignment.top_left,
                    end=ft.alignment.bottom_right,
                    colors=["#1a1a1a", "#0d0d0d"]
                ),
                content=ft.Column([
                    ft.Container(
                        content=ft.Row([
                            ft.Column([self.title, ft.Row([self.indicator, self.status], spacing=10)]),        
                            ft.Row([self.run_btn, self.next_btn], spacing=20)
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        padding=ft.padding.only(left=30, right=30, top=20, bottom=10)
                    ),
                    self._wrap_glass(ft.Row([
                        self.path_field,
                        ft.IconButton(ft.icons.FOLDER_OPEN_ROUNDED, on_click=lambda _: self.picker.get_directory_path()),
                        self.ar_selector
                    ], spacing=10), margin=ft.margin.symmetric(horizontal=30, vertical=5)),
                    ft.Container(self.tabs, expand=True, padding=ft.padding.only(left=20, right=20, bottom=20))
                ])
            )
        )

    def _section_label(self, text):
        return ft.Container(
            content=ft.Text(text, size=14, weight=ft.FontWeight.BOLD, color=ft.colors.GREY_400, style=ft.TextStyle(letter_spacing=1.2)),
            margin=ft.margin.only(left=40, top=10)
        )

    def _wrap_glass(self, content, height=None, expand=False, margin=None):
        return ft.Container(
            content=content, height=height, expand=expand,
            bgcolor=GLASS_BG, blur=ft.Blur(15, 15),
            border=ft.border.all(1, GLASS_BORDER), border_radius=20,
            padding=15, margin=margin or ft.margin.symmetric(horizontal=30, vertical=10)
        )

    def _on_path_selection(self, e: ft.FilePickerResultEvent):
        if e.path:
            self.path_field.value = e.path
            self.page.update()

    def _on_ar_switch(self, e):
        self.ar_mode = "9:16" if "9:16" in e.data else "16:9"

    def _write_log(self, val):
        self.log_content += f"{val}\n"
        self.log_field.value = self.log_content
        self.page.update()

    def _toggle_wait(self, state):
        self.indicator.bgcolor = ft.colors.AMBER if state else ft.colors.GREEN
        self.status.value = "Ожидание действий пользователя..." if state else "Активно"
        self.page.update()

    def _launch_engine(self):
        if self.active: return
        self.log_content = ""
        self.log_field.value = ""
        self.gallery_chars.controls.clear()
        self.gallery_images.controls.clear()
        self.gallery_videos.controls.clear()
        self.run_btn.disabled = True
        self.run_btn.bgcolor = ft.colors.GREY_800
        self.indicator.bgcolor = ft.colors.GREEN
        self.status.value = "Запуск движка..."
        self.active = True
        self.page.update()
        
        threading.Thread(target=self._executor, daemon=True).start()

    def _executor(self):
        root = self.path_field.value.strip() or os.getcwd()
        mode = self.ar_mode
        out_orig = sys.stdout
        sys.stdout = LogBridge(self._write_log)
        in_orig = builtins.input
        
        def ui_input():
            self._toggle_wait(True)
            self.nexus.clear()
            self.nexus.wait()
            self._toggle_wait(False)
            return ""
            
        builtins.input = ui_input
        
        try:
            if os.getcwd() not in sys.path: sys.path.insert(0, os.getcwd())
            import bot
            importlib.reload(bot)
            bot.main(ui_bridge=self._render_preview, base_dir=root, ar_mode=mode)
        except Exception as e:
            self._write_log(f"\n[ОШИБКА] {str(e)}")
            import traceback
            traceback.print_exc()
        finally:
            sys.stdout = out_orig
            builtins.input = in_orig
            self.active = False
            self.run_btn.disabled = False
            self.run_btn.bgcolor = ACCENT_COLOR
            self.indicator.bgcolor = ft.colors.GREY_700
            self.status.value = "Сессия завершена"
            self._write_log("\n[CORE] Pipeline terminated.")
            self.page.update()

    def _render_preview(self, name, variants, is_vid_legacy):
        if name is None:
            if self.pending_tasks:
                cmd = self.pending_tasks.pop(0)
                if cmd['action'] == 'save':
                    self.completed.add(cmd['name'])
                    self._sync_card(cmd['name'])
                return cmd
            return None

        # Determine stage
        target_gallery = self.gallery_chars
        if name.startswith("video_"): target_gallery = self.gallery_videos
        elif "_" in name and name.split("_")[0].isdigit(): target_gallery = self.gallery_images 
        elif name.isdigit(): target_gallery = self.gallery_images

        is_done = name in self.completed

        def post_cmd(act, v_idx=0):
            self.pending_tasks.append({"name": name, "action": act, "variant_index": v_idx})
            self._write_log(f"[UI] Запрос: {act.upper()} -> {name} (Вариант {v_idx})")

        def open_variant_selector(e):
            if is_done: return

            grid = ft.GridView(expand=True, runs_count=2, max_extent=450, child_aspect_ratio=0.85, spacing=20, run_spacing=20)
            for idx, v in enumerate(variants[:4]):
                v_data = v['b64']
                v_is_vid = v['is_vid']

                v_content = None
                if v_is_vid:
                    temp_v = os.path.join(self.temp_dir, f"preview_{name}_{idx}.mp4")
                    with open(temp_v, "wb") as f: f.write(base64.b64decode(v_data))
                    v_content = ft.Video(playlist=[ft.VideoMedia(temp_v)], autoplay=True, volume=0, expand=True)
                else:
                    v_content = ft.Image(src_base64=v_data, fit=ft.ImageFit.CONTAIN)

                grid.controls.append(
                    ft.Container(
                        content=ft.Column([
                            ft.Container(v_content, width=400, height=400, bgcolor=ft.colors.BLACK, border_radius=15, clip_behavior=ft.ClipBehavior.HARD_EDGE),
                            ft.ElevatedButton(
                                content=ft.Text(f"Выбрать вариант {idx+1}", size=14, weight=ft.FontWeight.BOLD),
                                style=ft.ButtonStyle(bgcolor=ACCENT_COLOR, color=ft.colors.WHITE),
                                width=400, height=50,
                                on_click=lambda _, i=idx, d=None: [post_cmd('save', i), self.page.close(dialog_ref)]      
                            )
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
                        padding=10, bgcolor=ft.colors.with_opacity(0.05, ft.colors.WHITE), border_radius=20    
                    )
                )

            dialog_ref = ft.AlertDialog(
                title=ft.Text(f"Выбор варианта для: {name}", size=20, weight=ft.FontWeight.BOLD),     
                content=ft.Container(grid, width=900, height=1000),
                actions=[
                    ft.TextButton("Регенерация", on_click=lambda _: [post_cmd('regen'), self.page.close(dialog_ref)]),
                    ft.TextButton("Закрыть", on_click=lambda _: self.page.close(dialog_ref))
                ]
            )
            self.page.overlay.append(dialog_ref)
            dialog_ref.open = True
            self.page.update()

        main_v = variants[0]
        thumb_content = None
        if main_v['is_vid']:
            temp_p = os.path.join(self.temp_dir, f"thumb_{name}.mp4")
            with open(temp_p, "wb") as f: f.write(base64.b64decode(main_v['b64']))
            thumb_content = ft.Video(playlist=[ft.VideoMedia(temp_p)], autoplay=True, volume=0, expand=True)   
        else:
            thumb_content = ft.Image(src_base64=main_v['b64'], fit=ft.ImageFit.COVER)

        card = ft.Container(
            content=ft.Stack([
                ft.Column([
                    ft.Container(thumb_content, width=200, height=200, bgcolor=ft.colors.BLACK, border_radius=15, clip_behavior=ft.ClipBehavior.HARD_EDGE),
                    ft.Text(name, size=11, weight=ft.FontWeight.W_600, text_align=ft.TextAlign.CENTER, width=200, no_wrap=True)
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Container(
                    ft.Icon(ft.icons.TOUCH_APP_ROUNDED, color=ft.colors.WHITE, size=30),
                    alignment=ft.alignment.center,
                    visible=not is_done,
                    bgcolor=ft.colors.with_opacity(0.3, ft.colors.BLACK)
                )
            ]),
            padding=10, border_radius=20, bgcolor=ft.colors.with_opacity(0.1, "#FFFFFF"),
            border=ft.border.all(3 if is_done else 1, ft.colors.GREEN_ACCENT if is_done else GLASS_BORDER),    
            width=220, height=240,
            on_click=open_variant_selector
        )

        # Search for existing card to update it
        found = False
        for i, c in enumerate(target_gallery.controls):
            try:
                if c.content.controls[0].controls[1].value == name:
                    target_gallery.controls[i] = card
                    found = True
                    break
            except: pass

        if not found:
            target_gallery.controls.append(card)
        
        self.page.update()
        return self.pending_tasks.pop(0) if self.pending_tasks else None

    def _sync_card(self, name):
        for g in [self.gallery_chars, self.gallery_images, self.gallery_videos]:
            for c in g.controls:
                try:
                    if c.content.controls[0].controls[1].value == name:
                        c.border = ft.border.all(3, ft.colors.GREEN_ACCENT)
                        c.content.controls[1].visible = False
                        self.page.update()
                        break
                except: pass

if __name__ == "__main__":
    ft.app(target=StudioApp)
