# 迁移记录

只在导出/换机时读，日常使用不加载。

## 依赖

- `android-a11y-cli`、`android-photos` —— Minis 内置，不用装
- `python3` —— Alpine 自带

## 前置条件

- **mshot 取屏替代路径仅用于 Android 10 及以下（SDK ≤ 29）**。Android 11+ 直接用
  `android-a11y-cli ui screenshot`，不要用 `mshot`。
- 用户需一次性设置：把「截屏」磁贴拖到通知栏**第一屏**，下拉即见。
  日常取屏失败的排查步骤见 `references/glitches.md`，这里只记换机时要做什么。

## 设计取舍（为什么不那么做）

- **不用 `ui screenshot`**：本机 Android 10，该 API 需 SDK 30，调用直接 NOT_SUPPORTED。
- **不用 `tap xy` 点磁贴**：磁贴位置会被用户随时拖动（实测 538 → 916 只隔几分钟），坐标必失效。
- **不直接读相册文件**：沙箱看不见 `/sdcard`，只能走 `android-photos export`。

## 硬编码值

| 值 | 位置 | 换机怎么重测 |
|---|---|---|
| `SHOT_DIR` | mshot.py 顶部 | 图片归档目录，默认 `/var/minis/workspace/shots/mshot`（工具独占，会清空超出的旧图）；对方无此目录会自动建 |
| `KEEP = 5` | mshot.py 顶部 | 只留最近 5 张。调大占地方，调小可能删掉还没看的图 |
| `TILE_X, TILE_Y` | mshot.py 顶部 | 「截屏」磁贴中心，本机 `(916, 363)`。换机或磁贴被拖动后：`ui dump` 找 text/desc 含「截屏」且 clickable 的节点，取其 `center` |
| `dismiss_shot_editor()` 的包名 | mshot.py | 本机是 `HwMultiScreenShot`。别的 ROM 可能没有截图编辑层，或包名不同——没有就让它永远不触发，不影响主流程 |

## 路径

- `/usr/local/bin/mshot` → 指向 `/var/minis/skills/mobile-ops/scripts/mshot.py`
- 若对方 Minis 的 skills 路径不同，改这个入口的第一行

- 入口库 `data/locators.json` **不要**带过去：里面是这台机器的 app 使用痕迹，
  对方没有同样的 app，选择器只会全是 stale。让他自己 `mloc learn`。
