# GalPie
语言： [**中文**] | [[English](./README_EN.md)]
<br><br>
基于PySide6的Galgame制作器<br>
<b>(仍在开发中)</b>
<br><br>
主程序：GaiPie.py<br>
目前可读取按照规则编写的剧情json文件来进行游戏<br>
（编写规则可查看 **doc** 文件夹中的 **剧情json规则.txt** ，亦可参考 **sample** 文件夹中的 **sample_create.json** 进行编写）<br>
<br>
将剧情json文件放入 **story** 文件夹内，程序将自动读取。<br>
<br>
游戏中的热键：<br>
<table>
<tr>
<td>[A]</td>
<td>自动播放</td>
</tr>
<tr>
<td>[Space]/[Enter]/鼠标左键点击</td>
<td>跳过此页</td>
</tr>
<tr>
<td>[F2]</td>
<td>快速存档（储存在 <b>saves</b> 文件夹内）</td>
</tr>
<tr>
<td>[F3]</td>
<td>快速读档（读取最新存档）</td>
</tr>
</table>
<br><br>
已知问题：<br>
1. 读档场景加载有误（已修复）<br>
2. 开始界面的开发尚未完成<br>
