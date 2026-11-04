# 迁移记录

只在导出/换机时读，日常使用不加载。

## 依赖

- `android-a11y-cli`、`android-photos` —— Minis 内置，不用装
- `python3` —— Alpine 自带

## 前置条件

- **仅 Android 10 及以下（SDK ≤ 29）**需要这套。Android 11+ 直接用
  `android-a11y-cli ui screenshot`，不要用 `mshot`。
- 用户需一次性设置：把「截屏」磁贴拖到通知栏**第一屏**，下拉即见。
  部分 ROM 叫「屏幕截图」「截取屏幕」，届时改 `mshot.py` 里 `tap text` 的参数。

## 设计取舍（为什么不那么做）

- **不用 `ui screenshot`**：本机 Android 10，该 API 需 SDK 30，调用直接 NOT_SUPPORTED。
- **不用 `tap xy` 点磁贴**：磁贴位置会被用户随时拖动（实测 538 → 916 只隔几分钟），坐标必失效。
- **等待定在 0.21 秒**：低于 200ms 时通知栏输入通道未就绪，点击被 InputDispatcher
  静默丢弃；180ms 是 50% 命中的赌博线，210ms 才稳。
- **不直接读相册文件**：沙箱看不见 `/sdcard`，只能走 `android-photos export`。

## 硬编码值

| 值 | 位置 | 换机怎么重测 |
|---|---|---|
| `WAIT = 0.21` | mshot.py 顶部 | 从 0.15 起每次 +0.03，连跑 3 次全成功就取该值；低于它时症状是"没报错也没图" |
| `tap text "截屏"` | mshot.py capture() | 展开通知栏 dump 一次，看磁贴实际叫什么 |
| `SHOT_DIR` | mshot.py 顶部 | 图片归档目录，默认 `/var/minis/workspace/shots`；对方无此目录会自动建 |
| `KEEP = 5` | mshot.py 顶部 | 只留最近 5 张。调大占地方，调小可能删掉还没看的图 |
| 延迟数字（49ms / 1.5s） | SKILL.md | 本机 HONOR Honor 手机 / Android 10 实测，别处只能当参考 |

## 路径

- `/usr/local/bin/mshot` → 指向 `/var/minis/skills/mobile-ops/scripts/mshot.py`
- 若对方 Minis 的 skills 路径不同，改这个入口的第一行

- 入口库 `data/locators.json` **不要**带过去：里面是这台机器的 app 使用痕迹，
  对方没有同样的 app，选择器只会全是 stale。让他自己 `mloc learn`。
