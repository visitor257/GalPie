# res_crypto —— 资源读取 / 解密接口

这是引擎里**唯一**的资源读取入口。开源版是"原样读文件"，你要加密资源，就改这一处。

```
res_crypto/
├── __init__.py     # 稳定入口（引擎只从这里 import，不要动）
├── decrypt.py      # ← 你要替换的文件
└── README.md       # 本说明
```

## 一、契约

| 项 | 约定 |
|---|---|
| 输入 | 业务层解析出的逻辑路径，如 `story/res/bg/park.png` |
| 输出 | **明文 bytes** |
| 异常 | 文件缺失/权限/解密失败 → 直接抛（`FileNotFoundError` / `OSError`） |
| 返回 `None` | **不要**。调用方按"抛异常"来兜底 |

引擎里三类资源都要过这里：

```python
# 剧情 JSON
data = json.loads(read_resource_bytes(path).decode("utf-8"))

# 图片
pixmap = QPixmap.loadFromData(read_resource_bytes(path))

# 音频
buf = QBuffer(); buf.setData(QByteArray(read_resource_bytes(path)))
```

## 二、文件读写永远走这一个函数

**不要**在引擎里加 `if 资源已加密:` 分支，也不要在别处 `open()` 资源文件。
加密与否只体现在 `decrypt.py` 的函数体里。

引擎里目前只有两类东西不走这里：用户数据（`.gpsave` / `.gpsetting` / `.gpreaded`）与
剧情入口文件（引擎根目录的 **EXORDIUM**，见下一节）。

## 二·补、剧情入口文件 EXORDIUM 也走这里

引擎根目录有一个无扩展名、全大写的明文文件 **EXORDIUM**，内容一行 = 剧情 JSON 的逻辑路径
（如 `story/sample_create.json`）。引擎读它也是调 `read_resource_bytes(EXORDIUM)`：

- 开源版：原样读，直接拿到那一行路径；
- 加密版：你可以在本函数里对 EXORDIUM 的内容一并做处理（轻度编码 / 映射），
  或让值写成一个“识别号”，再由本层的映射表换成真实文件。

引擎侧只有 `data_management/story_entry.py` 一个调用点，行为改动都集中在 `decrypt.py`。

## 三、替换步骤（创作者）

1. 打开 `decrypt.py`，把 `read_resource_bytes` 的实现换成你自己的（解密）。
2. 编译成扩展模块，发布包里用 `decrypt.pyd`（Linux 为 `.so`）替换 `decrypt.py`，
   **不要留 .py 源码**。

```bash
# Nuitka 示例
python -m nuitka --module res_crypto/decrypt.py --output-dir=res_crypto
```

## 四、三条硬规矩

1. **密钥不要硬编码成字符串**——运行时拼装 / 派生。硬编码的字符串 `strings` 一扫就露。
2. **实现要编译掉**——别把解密实现留在 .py 里发给玩家，等于白送。
3. **绝对不要"启动时一次性全解包到临时目录"**——玩家会直接去 temp 里捞。
   保持按需解密到内存。

补一条（加固到什么程度由你决定，引擎侧不参与）：只把 `decrypt.py` 换成 `.pyd`、
而引擎其余部分仍是明文 `.py` 时，玩家一行 `monkeypatch` 就能把本函数的返回值 dump 出来。
要真正抬高门槛，需要**整个客户端一起编译 / 加固**。

## 五、可选：路径改写

如果你的资源要改名（哈希名 / 随机名 / 换扩展名 / 换目录），
也在这个函数里做映射：

```python
def read_resource_bytes(path):
    real = MAP.get(path, path)      # story/res/bg/park.png -> data/9f3a.bin
    return decrypt(Path(real).read_bytes())
```

开源版是"原样打开"，加密版是"映射 + 解密"，两边接口不变。

## 六、性能提醒

本函数会真读磁盘 + 整段解密（实测：2MB 图片约 90ms、3MB 音频约 126ms，
纯 Python 原语）。所以：

- 图片请继续走 `ResourceManager` 的缓存（键 = 物理路径），别重复解密；
- 音频解密一次后把 bytes 留住，别每次播放重解；
- 翻页时可以在上一条语音播放期间预解密下一张图。

将来若真遇到 10MB+ 的大资源（长音频 / 视频），再加一个 `open_stream(path)`
的流式入口即可，共用同一套解密原语，不用改动现有调用点。
