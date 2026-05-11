import flet as ft
import threading
import sys
import os
import builtins
import importlib
import time

# --- ЦВЕТОВАЯ ПАЛИТРА GLASSMORPHISM ---
GLASS_BG = ft.colors.with_opacity(0.4, "#1F1F1F")
GLASS_BORDER_COLOR = ft.colors.with_opacity(0.15, "#FFFFFF")
ACCENT_BLUE = "#007AFF"

class RedirectStdOut:
    def __init__(self, log_fn):
        self.log_fn = log_fn
    def write(self, msg):
        if isinstance(msg, bytes):
            msg = msg.decode('utf-8', errors='replace')
        msg = msg.strip()
        if msg and not any(x in msg for x in ["browser_type", "node_modules", "=="]):
            self.log_fn(msg)
    def flush(self): pass
    def reconfigure(self, **kwargs): pass
    def detach(self): return self

class AutoGrokApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.wait_event = threading.Event()
        self.is_running = False
        self.mode_var = "2" # 1: 9:16, 2: 16:9
        self.command_queue = []
        self.saved_items = set()
        
        self.setup_ui()

    def setup_ui(self):
        self.page.title = "Auto Grok Studio"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.window_width = 850
        self.page.window_height = 950
        self.page.window_center()
        self.page.padding = 0
        self.page.spacing = 0
        self.page.bgcolor = ft.colors.BLACK

        # --- UI Components ---
        
        # Header
        self.title_text = ft.Text(
            "Auto Grok Studio",
            size=48,
            weight=ft.FontWeight.W_200, 
            color=ft.colors.WHITE,
            text_align=ft.TextAlign.CENTER
        )
        
        self.status_dot = ft.Container(width=10, height=10, border_radius=5, bgcolor=ft.colors.GREY_700)
        self.status_text = ft.Text("Ready", size=14, color=ft.colors.GREY_400)
        
        # Path Entry & Picker
        self.file_picker = ft.FilePicker(on_result=self.on_path_result)
        self.page.overlay.append(self.file_picker)

        self.path_input = ft.TextField(
            hint_text="Project path (leave empty for current folder)...",
            bgcolor=ft.colors.with_opacity(0.2, "#000000"),
            border_color=GLASS_BORDER_COLOR,
            border_radius=15,
            height=55,
            text_size=15,
            content_padding=ft.padding.only(left=20, top=0, right=20, bottom=0),
            expand=True,
            border_width=1
        )
        
        self.pick_btn = ft.IconButton(
            icon=ft.icons.FOLDER_OPEN_ROUNDED,
            icon_color=ft.colors.WHITE,
            on_click=lambda _: self.file_picker.get_directory_path()
        )
        
        # Mode Switcher
        self.mode_toggle = ft.SegmentedButton(
            selected={"16:9"},
            allow_multiple_selection=False,
            on_change=self.on_mode_change,
            segments=[
                ft.Segment(value="9:16", label=ft.Text("9:16", size=12)),
                ft.Segment(value="16:9", label=ft.Text("16:9", size=12)),
            ],
            show_selected_icon=False
        )

        # Log Console
        self.log_content = ft.ListView(expand=True, spacing=4, padding=10)
        
        # Gallery Preview
        self.gallery_row = ft.Row(
            spacing=10,
            scroll=ft.ScrollMode.ALWAYS,
        )

        # Action Buttons
        self.launch_btn = ft.ElevatedButton(
            content=ft.Text("Launch Session", size=16, weight=ft.FontWeight.BOLD),
            style=ft.ButtonStyle(
                color=ft.colors.WHITE,
                bgcolor=ACCENT_BLUE,
                shape=ft.RoundedRectangleBorder(radius=25),
            ),
            width=260,
            height=60,
            on_click=lambda _: self.start_bot()
        )
        
        self.confirm_btn = ft.OutlinedButton(
            content=ft.Text("Confirm", size=16, weight=ft.FontWeight.BOLD),
            style=ft.ButtonStyle(
                color=ft.colors.with_opacity(0.4, "#FFFFFF"),
                shape=ft.RoundedRectangleBorder(radius=25),
                side={ft.ControlState.DEFAULT: ft.BorderSide(1, GLASS_BORDER_COLOR)},
            ),
            width=200,
            height=60,
            disabled=True,
            on_click=lambda _: self.continue_bot()
        )

        # Layout Assembly
        self.page.add(
            ft.Container(
                expand=True,
                gradient=ft.LinearGradient(
                    begin=ft.alignment.top_left,
                    end=ft.alignment.bottom_right,
                    colors=["#0f0c29", "#302b63", "#24243e"],
                ),
                content=ft.Column(
                    controls=[
                        # Header Section
                        ft.Container(
                            content=ft.Column([
                                self.title_text,
                                ft.Row([self.status_dot, self.status_text], alignment=ft.MainAxisAlignment.CENTER, spacing=10)
                            ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                            margin=ft.margin.only(top=60, bottom=40),
                            alignment=ft.alignment.center
                        ),
                        
                        # Controls Panel
                        self.glass_panel(
                            content=ft.Row([
                                self.path_input,
                                self.pick_btn,
                                self.mode_toggle
                            ], spacing=10)
                        ),
                        
                        # Gallery Panel
                        self.glass_panel(
                            content=self.gallery_row,
                            height=180
                        ),
                        
                        # Console Panel
                        self.glass_panel(
                            content=self.log_content,
                            expand=True
                        ),
                        
                        # Footer Actions
                        ft.Container(
                            content=ft.Row([
                                self.launch_btn,
                                self.confirm_btn
                            ], alignment=ft.MainAxisAlignment.CENTER, spacing=30),
                            margin=ft.margin.only(bottom=60, top=20)
                        )
                    ],
                    expand=True
                )
            )
        )

    def on_path_result(self, e: ft.FilePickerResultEvent):
        if e.path:
            self.path_input.value = e.path
            self.page.update()
        else:
            self.log("📂 Выбор папки отменен.")

    def glass_panel(self, content, expand=False):
        return ft.Container(
            content=content,
            bgcolor=GLASS_BG,
            blur=ft.Blur(sigma_x=15, sigma_y=15),
            border=ft.border.all(1, GLASS_BORDER_COLOR),
            border_radius=20,
            padding=20,
            margin=ft.margin.symmetric(horizontal=30, vertical=15),
            expand=expand
        )

    def on_mode_change(self, e):
        # В стабильных версиях e.selection - это множество (set)
        self.mode_var = "1" if "9:16" in e.selection else "2"

    def log(self, msg):
        self.log_content.controls.append(
            ft.Text(msg, color="#D1D1D6", font_family="Consolas", size=12)
        )
        if len(self.log_content.controls) > 500:
            self.log_content.controls.pop(0)
        
        # Авто-прокрутка вниз
        self.log_content.scroll_to(offset=-1, duration=100)
        self.page.update()

    def enable_continue(self):
        self.confirm_btn.disabled = False
        self.confirm_btn.style.side = {ft.ControlState.DEFAULT: ft.BorderSide(2, ACCENT_BLUE)}
        self.confirm_btn.content.color = ft.colors.WHITE
        self.status_dot.bgcolor = ft.colors.ORANGE
        self.status_text.value = "Waiting"
        self.status_text.color = ft.colors.ORANGE
        self.log("\n[SYSTEM] Ready for next step. Click Confirm.")
        self.page.update()

    def continue_bot(self):
        self.confirm_btn.disabled = True
        self.confirm_btn.style.side = {ft.ControlState.DEFAULT: ft.BorderSide(1, GLASS_BORDER_COLOR)}
        self.confirm_btn.content.color = ft.colors.with_opacity(0.4, "#FFFFFF")
        self.status_dot.bgcolor = ft.colors.BLUE
        self.status_text.value = "Active"
        self.status_text.color = ft.colors.BLUE
        self.wait_event.set()
        self.page.update()

    def start_bot(self):
        if self.is_running: return
        self.log_content.controls.clear()
        self.launch_btn.disabled = True
        self.launch_btn.bgcolor = ft.colors.GREY_800
        self.status_dot.bgcolor = ft.colors.GREEN
        self.status_text.value = "Active"
        self.status_text.color = ft.colors.GREEN
        self.is_running = True
        self.wait_event.clear()
        self.page.update()
        
        self.log("🚀 Initializing Bot...")
        self.log("ℹ️ Make sure Chrome is CLOSED before launching.")
        
        threading.Thread(target=self.run_process, daemon=True).start()

    def run_process(self):
        base_dir = self.path_input.value.strip() or os.path.dirname(os.path.abspath(__file__))
        mode_choice = self.mode_var
        
        old_stdout = sys.stdout
        sys.stdout = RedirectStdOut(self.log)
        old_input = builtins.input
        
        def mock_input(prompt=""):
            if "папке проекта" in prompt: return base_dir
            if "вариант" in prompt: return mode_choice
            # Signal UI to enable "Confirm" button
            self.enable_continue()
            self.wait_event.wait()
            self.wait_event.clear()
            return ""
        
        builtins.input = mock_input
        
        try:
            if os.getcwd() not in sys.path: sys.path.insert(0, os.getcwd())
            import bot
            importlib.reload(bot)
            bot.main(preview_callback=self.handle_preview)
        except Exception as e:
            self.log(f"\n[ERROR] {str(e)}")
        finally:
            sys.stdout = old_stdout
            builtins.input = old_input
            self.on_finish()

    def on_finish(self):
        self.launch_btn.disabled = False
        self.launch_btn.bgcolor = ACCENT_BLUE
        self.confirm_btn.disabled = True
        self.confirm_btn.style.side = {ft.ControlState.DEFAULT: ft.BorderSide(1, GLASS_BORDER_COLOR)}
        self.status_dot.bgcolor = ft.colors.GREY_700
        self.status_text.value = "Ready"
        self.status_text.color = ft.colors.GREY_400
        self.is_running = False
        self.log("\n[FINISH] Process completed.")
        self.page.update()

    def handle_preview(self, name, data, is_video):
        # Если name - None, значит это опрос очереди команд от бота
        if name is None:
            if self.command_queue:
                cmd = self.command_queue.pop(0)
                if cmd['action'] == 'save':
                    self.saved_items.add(cmd['name'])
                    self.update_card_status(cmd['name'], True)
                return cmd
            return None

        is_b64 = data and not data.startswith("http")
        
        # Функция для кнопок
        def on_action(action_type):
            self.command_queue.append({"name": name, "action": action_type})
            self.log(f"🛠 GUI command: {action_type.upper()} for {name}")

        is_saved = name in self.saved_items
        border_color = ft.colors.GREEN_ACCENT if is_saved else GLASS_BORDER_COLOR
        border_width = 3 if is_saved else 1

        content_stack = ft.Stack([
            ft.Column([
                ft.Image(
                    src_base64=data if is_b64 else None,
                    src=data if (data and not is_b64) else None,
                    width=120, height=120, fit=ft.ImageFit.CONTAIN
                ) if not is_video else ft.Icon(ft.icons.VIDEOCAM_ROUNDED, color=ACCENT_BLUE, size=60),
                ft.Text(name, size=10, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER, width=120, no_wrap=False)
            ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            
            # Overlay Buttons (скрываем если уже сохранено)
            ft.Container(
                content=ft.Row([
                    ft.IconButton(
                        icon=ft.icons.SAVE_ROUNDED, 
                        icon_color=ft.colors.GREEN_ACCENT,
                        bgcolor=ft.colors.with_opacity(0.8, ft.colors.BLACK),
                        on_click=lambda _: on_action('save'),
                        tooltip="Save this version"
                    ),
                    ft.IconButton(
                        icon=ft.icons.REFRESH_ROUNDED, 
                        icon_color=ft.colors.ORANGE_ACCENT,
                        bgcolor=ft.colors.with_opacity(0.8, ft.colors.BLACK),
                        on_click=lambda _: on_action('regen'),
                        tooltip="Regenerate"
                    ),
                ], alignment=ft.MainAxisAlignment.CENTER, spacing=0),
                alignment=ft.alignment.bottom_center,
                padding=ft.padding.only(bottom=25),
                visible=not is_saved
            )
        ])

        preview = ft.Container(
            content=content_stack,
            padding=5, border_radius=15, 
            bgcolor=ft.colors.with_opacity(0.1, "#FFFFFF"),
            border=ft.border.all(border_width, border_color),
            width=140,
            height=160
        )
        
        # Проверяем, нет ли уже такого имени в галерее
        found = False
        for i, ctrl in enumerate(self.gallery_row.controls):
            try:
                ctrl_name = ctrl.content.controls[0].controls[1].value
                if ctrl_name == name:
                    self.gallery_row.controls[i] = preview
                    found = True
                    break
            except: pass

        if not found:
            self.gallery_row.controls.insert(0, preview)
            if len(self.gallery_row.controls) > 30:
                self.gallery_row.controls.pop()
        
        self.page.update()
        
        if self.command_queue:
            cmd = self.command_queue.pop(0)
            if cmd['action'] == 'save':
                self.saved_items.add(cmd['name'])
                self.update_card_status(cmd['name'], True)
            return cmd
        return None

    def update_card_status(self, name, is_saved):
        for ctrl in self.gallery_row.controls:
            try:
                ctrl_name = ctrl.content.controls[0].controls[1].value
                if ctrl_name == name:
                    ctrl.border = ft.border.all(3, ft.colors.GREEN_ACCENT)
                    # Скрываем кнопки
                    ctrl.content.controls[1].visible = False
                    self.page.update()
                    break
            except: pass

if __name__ == "__main__":
    ft.app(target=AutoGrokApp)
