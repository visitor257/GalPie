# GalPie
Language： [[中文](./README.md)] | [**English**]
<br><br>
A galgame maker/reader with PySide6<br>
<b>(Still developing)</b>
<br><br>
Main Program: GaiPie.py<br>
It can currently read story JSON files written according to the rules to play the game.<br>
(For writing rules, please refer to **Story JSON rules.txt** in the **doc** folder. You can also consult **sample_create.json** in the **sample** folder as a reference when writing.)<br>
<br>
Put the story JSON file into the **story** folder, and the program will then load it automatically.<br>
<br>
Hotkeys in the game:  <br>
<table>  
<tr>  
<td>[A]</td>  
<td>Auto-play</td>  
</tr>  
<tr>  
<td>[Space]/[Enter]/Left Mouse Click</td>  
<td>Advance the page</td>  
</tr>  
<tr>  
<td>[F2]</td>  
<td>Fast save (Saves are stored in the <b>saves</b> folder)</td>  
</tr>  
<tr>  
<td>[F3]</td>  
<td>Quick load (load the newest save)</td>  
</tr>  
</table>
<br><br>
Known bugs: <br>
1. Scene does not match the loaded save. (Fixing)
