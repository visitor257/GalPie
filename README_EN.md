# GalPie
Language: [中文](./README.md) | [**English**]
<br><br>
A galgame maker/reader based on PySide6<br>
<b>(Still under development)</b>
<br><br>
Main program: GalPie.py<br>
It can currently read story JSON files written according to the rules to play the game.<br>
(For the writing rules, please refer to **Story JSON rules.txt** (Chinese: **剧情json规则.txt**) in the **doc** folder. You can also consult **sample_create.json** in the **story** folder as a reference when writing.)<br>
<br>
Put the story JSON file into the **story** folder, and the program will load it automatically on startup.<br>
If the story includes a **menu** (main menu), the main menu is shown first on launch; otherwise the story starts directly.<br>
<br>

## Main Menu<br>
On launch, if the story has a **menu** configured, the main menu is shown first. It supports the following buttons (configured in **menu.menu_pos**):<br>
- **Continue** (qload): If a save exists, a confirm dialog is shown; after confirmation it loads the newest save (quick save first) and enters the story. If no save exists, clicking does nothing.<br>
- **Start** (start): Enter the story<br>
- **Load** (load): Open the load game panel to load a slot save of this story<br>
- **Settings** (settings): Open the settings panel (language / resolution)<br>
- **Quit** (quit): Show a confirm dialog; exit the program after confirmation<br>
<br>

## In-Game Controls<br>
<table>
<tr>
<td>[Space] / [Enter] / Left Mouse Click</td>
<td>Advance the story (clicking while the text is still typing shows the full text immediately)</td>
</tr>
<tr>
<td>Right Mouse Click</td>
<td>While a Settings / Backlog / Save / Load panel is open, equivalent to pressing that panel's "Back" button</td>
</tr>
<tr>
<td>[A]</td>
<td>Toggle Auto-play</td>
</tr>
<tr>
<td>[S]</td>
<td>Toggle Skip (quickly advances the story; only the first scene of each page is played)</td>
</tr>
<tr>
<td>[F2]</td>
<td>Save (to save slot 0)</td>
</tr>
<tr>
<td>[F3]</td>
<td>Load (loads the newest save; quick save takes priority)</td>
</tr>
<tr>
<td>[Esc]</td>
<td>Close the currently open panel (Settings / Backlog / Save / Load)</td>
</tr>
</table>
<br>

## Bottom Menu Bar<br>
During the story, a preset menu bar can be shown at the bottom of the window (controlled by the story's **ui.bottom_menu**). From right to left:<br>
<b>⊙</b> (hide toggle: hides the dialogue box and the bottom menu; click anywhere to restore) → <b>Log</b> (backlog of past dialogue) → <b>Settings</b> (language/resolution) → <b>Skip (▷▷)</b> toggle → <b>Auto-play (▷)</b> toggle → <b>Load</b> (opens the load panel) → <b>Save</b> (opens the save panel) → <b>Q.Load</b> (quick load: confirm, then load the newest save) → <b>Q.Save</b> (quick save).<br>
<b>⊙</b> hides the dialogue box and the whole bottom menu (including the bar itself) while the story keeps advancing; pressing anywhere (left or right click) restores them, with the dialogue box restored to its visibility before hiding.<br>
Skip and Auto-play are mutually exclusive (enabling one automatically disables the other); opening any panel pauses both, and they resume after returning to the story.<br>
The colors of the menu bar, its buttons, and all panels can be configured in the story JSON (see the rules documents in the **doc** folder).<br>
<br>

## Settings Panel<br>
Click the **Settings** button in the bottom menu during the story, or the **settings** button in the main menu if configured, to open the settings panel:<br>
- **Language**: Switch the game language (options come from settings.language in the story JSON; preset UI text supports Chinese/English/Japanese, falling back to English out of range; in-story dialogue is shown in the translations provided by the story)<br>
- **Resolution**: Switch the window resolution (options come from settings.window_size in the story JSON, with a "Fullscreen" option appended at the end; the built-in default list is used when not configured)<br>
Settings are saved automatically to a settings file and restored the next time the same story is launched.<br>
<br>

## Save / Load Panel<br>
Click the **Save** button in the bottom menu during the story to open the save panel, or click **Load** on the main menu to open the load panel (both share the same grid-based interface):<br>
- **Slot saves**: 8 slots per page (2 rows × 4 columns). Clicking an empty slot saves to it; clicking a slot that already has a save asks "Confirm overwrite?" first, then overwrites after confirmation<br>
- **Delete save**: Slots with a save have a trash button at the bottom-right; clicking it asks "Confirm delete?", then deletes the save after confirmation<br>
- **Paging**: ◀ ▶ at the bottom-left flip pages (circular), showing "current page/total pages"; the save panel has a **+** button to add a page, the load panel does not<br>
- **Load panel**: Clicking a slot that has a save asks "Confirm load?", then loads that save and enters the story (quick saves do not appear in the slots)<br>
- At the bottom-right there are **Main Menu** (return to the main menu) and **Back** (return to the story) buttons<br>
<br>

## Backlog Panel<br>
Click the **Log** button in the bottom menu to open it and view the dialogue history of the current session (shown in the current language); the Back button closes the panel.<br>
<br>

## Save System<br>
Save files are stored in the **saves** folder and are isolated per story automatically (the file name prefix is story title_identify code):<br>
- **Slot saves**: `{title}_{identify_code}_SLOT{index}.gpsave` (index is the slot number, e.g., 0-7)<br>
- **Quick save**: `{title}_{identify_code}_QSAVE.gpsave` (takes priority when loading with F3)<br>
- **Settings file**: `{title}_{identify_code}_SETTINGS.gpsetting` (stores language/resolution settings)<br>
Saves of different stories do not interfere with each other; <b>please give different stories different identify_code values</b>, otherwise they are treated as the same story and share saves.<br>
<br>
