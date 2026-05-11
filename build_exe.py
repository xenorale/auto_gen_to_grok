import PyInstaller.__main__
import os
import sys

def build():
    icon_path = "icon.ico"
    if not os.path.exists(icon_path):
        icon_path = None
        print("⚠️ Иконка icon.ico не найдена, собираю со стандартной.")

    params = [
        'gui.py',
        '--name=AutoGrokStudio',
        '--onedir', # Рекомендую onedir для Playwright, так стабильнее
        '--windowed', # Без консоли
        '--noconfirm',
        '--clean',
        '--add-data=bot.py;.', # Добавляем логику бота внутрь
        '--hidden-import=playwright',
        '--hidden-import=playwright_stealth',
        '--hidden-import=flet',
    ]

    if icon_path:
        params.append(f'--icon={icon_path}')

    print("🚀 Начинаю сборку EXE...")
    PyInstaller.__main__.run(params)
    print("\n✅ Сборка завершена! Ищи файл в папке dist/AutoGrokStudio")

if __name__ == "__main__":
    try:
        import PyInstaller
    except ImportError:
        print("❌ Ошибка: PyInstaller не установлен. Выполни: pip install pyinstaller")
        sys.exit(1)
    build()
