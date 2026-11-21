# 安装

## 前置条件

| 需要什么 | 说明 | 缺了会怎样 |
|---|---|---|
| Android 手机 | 本包按 Android 17 实测（launcher `com.miui.home`） | 换机会影响桌面网格与坐标 |
| python3 ≥ 3.7 | `scr` / `bw` 只用标准库 | 命令起不来 |
| 宿主的无障碍 CLI | `android-a11y-cli`（`ui dump / tap / input / gesture`） | `screen` 全线不可用 |
| 宿主其他 CLI | `android-open`、`android-device`、`android-photos`（可选 `android-shizuku-cli`） | 开 App / 设备信息 / 截图功能降级 |
| X 浏览器 | 包名 `com.mmbox.xbrowser` | `x-browser` 不可用 |

> 这些 `android-*` 命令由宿主 App（本包在 Minis 上开发）提供。换宿主需自行实现等价命令；
> 只想用浏览器那一半的话，不需要无障碍服务。

## 一键装

```bash
sh install.sh                 # 装到 /usr/local/bin
sh install.sh --bin ~/.local/bin
```

做三件事：查依赖 → `scr` / `bw` 软链进 PATH → 各跑一次体检（`scr doctor`、`bw state`）。

## 手动装

```bash
chmod +x skills/screen/scr skills/x-browser/bw
ln -sf "$PWD/skills/screen/scr"    /usr/local/bin/scr
ln -sf "$PWD/skills/x-browser/bw"  /usr/local/bin/bw
```

## 首次使用

1. **开无障碍**：设置 → 无障碍 → 本 App。验证 `scr doctor`（退出码 69 = 服务没开）。
2. **校准桌面网格**（只有整理桌面才需要）：`scr doctor --save` 把实测值写进 `skills/screen/device.json`。

## 验收

```bash
scr state                 # 前台包名 + 条目数
scr look                  # 这一屏的节点清单
bw state                  # 浏览器是否就绪
bw go https://example.com && bw read
```

## 排错

| 现象 | 含义 | 处理 |
|---|---|---|
| 退出码 69 / `SERVICE_NOT_RUNNING` | 无障碍没开 | 去设置里打开 |
| `✘ 当前屏 N 项里没有 "X"` | 这一屏确实没有 | 回滚或换个叫法，别猜着点 |
| `✘ 无法确定 "X"，命中 N 个` | 文字有歧义 | `--nth N` 或快照里的 `sN` |
| `✘ 该窗口禁止截屏` | FLAG_SECURE | 停手，交给人 |
| `? … 未确认` | 只能看像素，判不准 | 用 `scr shot` 定夺，别当成"没动" |
| `bw` 报 `没关标签`(exit 3) | 浏览器不在前台 | 切回前台再 close |
| `bw fast` 拿回不到 200 字 | 多半是登录墙 | 改用 `bw go`（两条路 cookie 不互通） |

更多：`skills/screen/迁移.md`（部署顺序/换机）、`skills/x-browser/迁移.md`（浏览器接线与已知限制）。

## 卸载

```bash
rm -f /usr/local/bin/{scr,bw}
```
