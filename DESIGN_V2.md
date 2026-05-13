# Design Document: Auto Grok Studio v2

## Goal
Enhance the user experience by introducing a tabbed interface, a copyable log, and a multi-variant selection workflow for generated media.

## 1. User Interface (gui.py)
### 1.1 Tabs
- **Tab 1: Materials (Материалы)**
  - Organized gallery of generated cards.
  - Clicking a card opens a selection modal.
- **Tab 2: Log (Лог)**
  - A full-height `ft.TextField` (multiline, read-only) containing the raw system output.
  - Includes a "Copy to Clipboard" button.

### 1.2 Interactive Selection
- When Grok generates media (2-4 items), the UI card will display the first variant as a thumbnail.
- **Selection Modal (`ft.AlertDialog`):**
  - Displays all 2-4 variants in a grid.
  - Each variant has a "Select" button.
  - "Regenerate" button to retry the entire prompt.

## 2. Bot Logic (bot.py)
### 2.1 Media Capture Enhancement
- Update `capture_media` and `sync_previews` to detect all generated images/videos in the current response block.
- Instead of returning a single `b64` string, return a list of variants.
- For videos, continue using the temporary file path strategy.

### 2.2 Precise Saving
- The `save` command from the UI will now include an `index` or `id` to ensure the correct variant is moved to the final destination folder.

## 3. Workflow Stages
- The gallery will be divided into sections:
  1. **Characters (Персонажи)**
  2. **Scenes: Images (Сцены: Изображения)**
  3. **Scenes: Videos (Сцены: Видео)**

## 4. Technical Strategy
- **State Management:** Use a dictionary to track task statuses and their multiple variants.
- **Async Bridge:** Maintain the `threading.Event` and `pending_tasks` queue but expand them to support multi-choice payloads.
- **Headless Mode:** Retain the headless default to keep the workspace clean.
