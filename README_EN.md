# GalPie
Language: [中文](./README.md) | [**English**]
<br><br>
A galgame maker/reader based on PySide6<br>
<b>(Still under development)</b>
<br><br>
Main program: GalPie.py<br>
It can currently read story JSON files written according to the rules to play the game.<br>
(For the writing rules, please refer to **Story JSON rules.txt** (Chinese: **剧情json规则.txt**) in the **doc** folder. You can also consult **sample_create.json** in the **sample** folder as a reference when writing.)<br>
<br>
Put the story JSON file into the **story** folder, and the program will load it automatically on startup.<br>
If the story includes a **menu** (main menu), the main menu is shown first on launch and the story starts after clicking the **Start Game** button; otherwise the story starts directly.<br>
<br>

## In-Game Controls<br>
<table>
<tr>
<td>[Space] / [Enter] / Left Mouse Click</td>
<td>Advance the story (clicking while the text is still typing shows the full text immediately)</td>
</tr>
<tr>
<td>[A]</td>
<td>Toggle Auto-play</td>
</tr>
<tr>
<td>[S]</td>
<td>Toggle Skip (simulates holding down Space to advance quickly)</td>
</tr>
<tr>
<td>[F2]</td>
<td>Quick save (saves are stored in the <b>saves</b> folder)</td>
</tr>
<tr>
<td>[F3]</td>
<td>Quick load (loads the newest save)</td>
</tr>
<tr>
<td>[Esc]</td>
<td>Close the settings panel</td>
</tr>
</table>
<br>
During the story, a preset menu bar can be shown at the bottom of the window (controlled by the story's **ui.bottom_menu**). From right to left:<br>
<b>Settings</b> button (opens the settings panel; switch language/resolution, etc.) → <b>Skip (▷▷)</b> toggle → <b>Auto-play (▷)</b> toggle.<br>
Skip and Auto-play are mutually exclusive (enabling one automatically disables the other); opening the settings panel pauses both, and they resume after returning to the story.<br>
<br>

## Settings Panel<br>
Click the **Settings** button in the bottom menu during the story, or the **settings** button in the main menu if configured, to open the settings panel:<br>
- **Language**: Switch the game language (options come from settings.language in the story JSON; UI text supports Chinese/English/Japanese, falling back to English out of range)<br>
- **Resolution**: Switch the window resolution (options come from settings.window_size in the story JSON, with a "Fullscreen" option appended at the end; the built-in default list is used when not configured)<br>
<br>

## Known Issues<br>
1. Scene does not match the loaded save. (Fixed)<br>
