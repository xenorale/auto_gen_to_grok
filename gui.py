import flet as ft
import threading
import sys
import os
import builtins
import importlib
import time

ACCENT_COLOR = "#007AFF"
GLASS_BG = ft.colors.with_opacity(0.4, "#1F1F1F")
GLASS_BORDER = ft.colors.with_opacity(0.15, "#FFFFFF")

class LogBridge:
    def __init__(self, sink):
        self.sink = sink
    def write(self, buf):
        if isinstance(buf, bytes):
            buf = buf.decode('utf-8', errors='replace')
        val = buf.strip()
        if val and not any(x in val for x in ["browser_type", "node_modules", "=="]):
            self.sink(val)
    def flush(self): pass
    def reconfigure(self, **kwargs): pass
    def detach(self): return self

class StudioApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.nexus = threading.Event()
        self.active = False
        self.ar_mode = "2"
        self.pending_tasks = []
        self.completed = set()
        self._build_interface()

    def _build_interface(self):
        self.page.title = "Auto Grok Studio"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.window_width = 850
        self.page.window_height = 950
        self.page.window_center()
        self.page.padding = 0
        self.page.bgcolor = ft.colors.BLACK

        self.title = ft.Text("Auto Grok Studio", size=48, weight=ft.FontWeight.W_200, color=ft.colors.WHITE)
        self.indicator = ft.Container(width=10, height=10, border_radius=5, bgcolor=ft.colors.GREY_700)
        self.status = ft.Text("Ready", size=14, color=ft.colors.GREY_400)

        self.picker = ft.FilePicker(on_result=self._on_path_selection)
        self.page.overlay.append(self.picker)

        self.path_field = ft.TextField(
            hint_text="Project destination...",
            bgcolor=ft.colors.with_opacity(0.2, "#000000"),
            border_color=GLASS_BORDER,
            border_radius=15,
            height=55,
            expand=True,
            border_width=1
        )

        self.ar_selector = ft.SegmentedButton(
            selected={"16:9"},
            allow_multiple_selection=False,
            on_change=self._on_ar_switch,
            segments=[
                ft.Segment(value="9:16", label=ft.Text("9:16", size=12)),
                ft.Segment(value="16:9", label=ft.Text("16:9", size=12)),
            ],
            show_selected_icon=False
        )

        self.console = ft.ListView(expand=True, spacing=4, padding=10)
        self.gallery = ft.Row(spacing=10, scroll=ft.ScrollMode.ALWAYS)

        self.run_btn = ft.ElevatedButton(
            content=ft.Text("Launch Session", size=16, weight=ft.FontWeight.BOLD),
            style=ft.ButtonStyle(color=ft.colors.WHITE, bgcolor=ACCENT_COLOR, shape=ft.RoundedRectangleBorder(radius=25)),
            width=260, height=60, on_click=lambda _: self._launch_engine()
        )

        self.next_btn = ft.OutlinedButton(
            content=ft.Text("Confirm", size=16, weight=ft.FontWeight.BOLD),
            style=ft.ButtonStyle(
                color=ft.colors.with_opacity(0.4, "#FFFFFF"),
                shape=ft.RoundedRectangleBorder(radius=25),
                side={ft.ControlState.DEFAULT: ft.BorderSide(1, GLASS_BORDER)},
            ),
            width=200, height=60, disabled=True, on_click=lambda _: self._resume_flow()
        )

        self.page.add(
            ft.Container(
                expand=True,
                gradient=ft.LinearGradient(
                    begin=ft.alignment.top_left, end=ft.alignment.bottom_right,
                    colors=["#0f0c29", "#302b63", "#24243e"]
                ),
                content=ft.Column([
                    ft.Container(
                        content=ft.Column([
                            self.title,
                            ft.Row([self.indicator, self.status], alignment=ft.MainAxisAlignment.CENTER, spacing=10)
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                        margin=ft.margin.only(top=60, bottom=40)
                    ),
                    self._wrap_glass(ft.Row([
                        self.path_field,
                        ft.IconButton(ft.icons.FOLDER_OPEN_ROUNDED, on_click=lambda _: self.picker.get_directory_path()),
                        self.ar_selector
                    ], spacing=10)),
                    self._wrap_glass(self.gallery, height=180),
                    self._wrap_glass(self.console, expand=True),
                    ft.Container(
                        content=ft.Row([self.run_btn, self.next_btn], alignment=ft.MainAxisAlignment.CENTER, spacing=30),
                        margin=ft.margin.only(bottom=60, top=20)
                    )
                ])
            )
        )

    def _wrap_glass(self, content, height=None, expand=False):
        return ft.Container(
            content=content, height=height, expand=expand,
            bgcolor=GLASS_BG, blur=ft.Blur(15, 15),
            border=ft.border.all(1, GLASS_BORDER), border_radius=20,
            padding=20, margin=ft.margin.symmetric(horizontal=30, vertical=15)
        )

    def _on_path_selection(self, e: ft.FilePickerResultEvent):
        if e.path:
            self.path_field.value = e.path
            self.page.update()

    def _on_ar_switch(self, e):
        self.ar_mode = "1" if "9:16" in e.selection else "2"

    def _write_log(self, val):
        self.console.controls.append(ft.Text(val, color="#D1D1D6", font_family="Consolas", size=12))
        if len(self.console.controls) > 500: self.console.controls.pop(0)
        self.console.scroll_to(offset=-1, duration=100)
        self.page.update()

    def _toggle_wait(self, state):
        self.next_btn.disabled = not state
        self.next_btn.style.side = {ft.ControlState.DEFAULT: ft.BorderSide(2, ACCENT_COLOR if state else GLASS_BORDER)}
        self.next_btn.content.color = ft.colors.WHITE if state else ft.colors.with_opacity(0.4, "#FFFFFF")
        self.indicator.bgcolor = ft.colors.ORANGE if state else ft.colors.BLUE
        self.status.value = "Waiting" if state else "Active"
        self.status.color = ft.colors.ORANGE if state else ft.colors.BLUE
        if state: self._write_log("\n[CORE] System idle. Interaction required.")
        self.page.update()

    def _resume_flow(self):
        self._toggle_wait(False)
        self.nexus.set()

    def _launch_engine(self):
        if self.active: return
        self.console.controls.clear()
        self.gallery.controls.clear()
        self.run_btn.disabled = True
        self.run_btn.bgcolor = ft.colors.GREY_800
        self.indicator.bgcolor = ft.colors.GREEN
        self.status.value = "Active"
        self.status.color = ft.colors.GREEN
        self.active = True
        self.nexus.clear()
        self.page.update()
        threading.Thread(target=self._executor, daemon=True).start()

    def _executor(self):
        root = self.path_field.value.strip() or os.path.dirname(os.path.abspath(__file__))
        mode = self.ar_mode
        out_orig = sys.stdout
        sys.stdout = LogBridge(self._write_log)
        in_orig = builtins.input
        
        def bridge_input(prompt=""):
            if "папке проекта" in prompt: return root
            if "вариант" in prompt: return mode
            self._toggle_wait(True)
            self.nexus.wait()
            self.nexus.clear()
            return ""
        
        builtins.input = bridge_input
        try:
            if os.getcwd() not in sys.path: sys.path.insert(0, os.getcwd())
            import bot
            importlib.reload(bot)
            bot.main(ui_bridge=self._render_preview)
        except Exception as e:
            self._write_log(f"\n[FAULT] {str(e)}")
        finally:
            sys.stdout = out_orig
            builtins.input = in_orig
            self._finalize()

    def _finalize(self):
        self.run_btn.disabled = False
        self.run_btn.bgcolor = ACCENT_COLOR
        self.next_btn.disabled = True
        self.indicator.bgcolor = ft.colors.GREY_700
        self.status.value = "Ready"
        self.active = False
        self._write_log("\n[CORE] Pipeline terminated.")
        self.page.update()

    def _render_preview(self, name, data, is_vid):
        if name is None:
            if self.pending_tasks:
                cmd = self.pending_tasks.pop(0)
                if cmd['action'] == 'save':
                    self.completed.add(cmd['name'])
                    self._sync_card(cmd['name'])
                return cmd
            return None

        is_b64 = data and not data.startswith("http")
        is_done = name in self.completed

        def post_cmd(act):
            self.pending_tasks.append({"name": name, "action": act})
            self._write_log(f"[UI] Request: {act.upper()} -> {name}")

        stack = ft.Stack([
            ft.Column([
                ft.Image(src_base64=data if is_b64 else None, src=data if (data and not is_b64) else None,
                         width=120, height=120, fit=ft.ImageFit.CONTAIN) if not is_vid else 
                ft.Icon(ft.icons.VIDEOCAM_ROUNDED, color=ACCENT_COLOR, size=60),
                ft.Text(name, size=10, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER, width=120)
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Container(
                content=ft.Row([
                    ft.IconButton(ft.icons.SAVE_ROUNDED, icon_color=ft.colors.GREEN_ACCENT, 
                                  bgcolor=ft.colors.with_opacity(0.8, ft.colors.BLACK), on_click=lambda _: post_cmd('save')),
                    ft.IconButton(ft.icons.REFRESH_ROUNDED, icon_color=ft.colors.ORANGE_ACCENT, 
                                  bgcolor=ft.colors.with_opacity(0.8, ft.colors.BLACK), on_click=lambda _: post_cmd('regen')),
                ], alignment=ft.MainAxisAlignment.CENTER),
                alignment=ft.alignment.bottom_center, padding=ft.padding.only(bottom=25), visible=not is_done
            )
        ])

        card = ft.Container(
            content=stack, padding=5, border_radius=15, bgcolor=ft.colors.with_opacity(0.1, "#FFFFFF"),
            border=ft.border.all(3 if is_done else 1, ft.colors.GREEN_ACCENT if is_done else GLASS_BORDER),
            width=140, height=160
        )

        for i, c in enumerate(self.gallery.controls):
            try:
                if c.content.controls[0].controls[1].value == name:
                    self.gallery.controls[i] = card
                    self.page.update()
                    return self.pending_tasks.pop(0) if self.pending_tasks else None
            except: pass

        self.gallery.controls.insert(0, card)
        if len(self.gallery.controls) > 30: self.gallery.controls.pop()
        self.page.update()
        return self.pending_tasks.pop(0) if self.pending_tasks else None

    def _sync_card(self, name):
        for c in self.gallery.controls:
            try:
                if c.content.controls[0].controls[1].value == name:
                    c.border = ft.border.all(3, ft.colors.GREEN_ACCENT)
                    c.content.controls[1].visible = False
                    self.page.update()
                    break
            except: pass

if __name__ == "__main__":
    ft.app(target=StudioApp)
