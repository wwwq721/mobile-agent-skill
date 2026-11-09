# 安装

## 前置条件

| 需要什么 | 说明 | 缺了会怎样 |
|---|---|---|
| Android 手机 | 本包按 Android ≤10 调过；11+ 可直接用宿主自带 `ui screenshot` | `mshot` 用不上 |
| python3 ≥ 3.7 + curl | 桥、格式化器、脚本都靠它 | 全部不可用 |
| 手机浏览器 | X 浏览器（`com.mmbox.xbrowser`）实测；其它内核 76–87 的浏览器也能跑 | `xb` 无标签 |
| 用户脚本管理器 | 油猴 / 篡改猴类插件 | 脚本注不进去，`xb` 全部超时 |
| 宿主的无障碍 CLI | 本包按 `android-a11y-cli` 编写 | `mobile-ops` 不可用（浏览器那半不受影响） |

> `android-a11y-cli`、`android-clipboard`、`minis-scheduled` 由宿主 App（Minis）提供。
> 换宿主需自行实现等价命令；只想要浏览器那一半的话，不需要无障碍。

## 一键装

```bash
sh install.sh                 # 装到 /usr/local/bin
sh install.sh --bin ~/.local/bin
```

做四件事：查依赖 → `xb`/`mshot`/`mloc` 软链进 PATH → 起 8765 桥 → `xb status` 自检。

## 手动装

```bash
chmod +x skills/phone-browser/xb/xb.sh skills/phone-browser/bridge/restart.sh \
         skills/mobile-ops/scripts/{mshot,mloc}.py
ln -sf "$PWD/skills/phone-browser/xb/xb.sh"      /usr/local/bin/xb
ln -sf "$PWD/skills/mobile-ops/scripts/mshot.py" /usr/local/bin/mshot
ln -sf "$PWD/skills/mobile-ops/scripts/mloc.py"  /usr/local/bin/mloc
sh skills/phone-browser/bridge/restart.sh
```

## 装完还要人工做

1. **装用户脚本**：手机浏览器打开 `http://127.0.0.1:8765/xb.user.js`，安装；**装之前就开着的标签要刷新一次**。
2. **开无障碍**（只有 `mobile-ops` 需要）：设置 → 无障碍 → 本 App，验证 `android-a11y-cli service ping`。

## 验收

```bash
xb status                  # ok sv=3.9.x tabs=1 pending=0 → 桥 + 脚本都通了
xb open 'https://example.com/'
xb js 'document.title'     # 0.1s 回标题
mshot                      # 返回截图路径（Android ≤10）
```

## 排错

| 现象 | 原因 | 处理 |
|---|---|---|
| `xb status` 没响应 | 桥没起 | `sh skills/phone-browser/bridge/restart.sh` |
| `没有标签` | 浏览器没开 / 被后台杀掉 | 用 `xb open <url>` 拉起 |
| 标签 `脚本旧` | 那页跑的是旧脚本 | 刷新页面 |
| `后台` / `raf=0` | 页面被冻结（含息屏、别的 App 在前台） | 把浏览器切前台，或"打开→做→取"压进同一条命令 |
| `needs_foreground`(409) | 匹配的标签都隐藏 | 同上，不是故障 |
| `no element` / `ambiguous selector` | 选择器 0 个或多个 | 用 `xb snapshot` 给的可点 ref |
| `fill_rejected` | 控件拒收该值（含富文本） | 不重试；富文本不在范围内 |
| 命令打到了用户在用的页面 | 桥只投给最可见的标签 | 先 `xb js 'location.href'` 确认，再决定是否 `--new` |

更多细节见 `skills/phone-browser/references/internals.md`。

## 卸载

```bash
rm -f /usr/local/bin/{xb,mshot,mloc}
pkill -f 'phone-browser/bridge/bridge.py'
```
