# 安装

两条路线：**一键脚本**（推荐）或**手动装**（想看清每一步时用）。

## 前置条件

| 需要什么 | 说明 | 缺了会怎样 |
|---|---|---|
| Android ≤ 10 的手机 | 11+ 可直接用宿主自带的 `ui screenshot` | `mshot` 用不上，改用 `ui screenshot` |
| 宿主的无障碍 CLI | 本包按 `android-a11y-cli` 编写（`ui dump` / `tap` / `input` / `gesture`） | `mobile-ops` 全线不可用 |
| python3 ≥ 3.7 | 桥、MCP server、脚本都靠它 | `edge` / 桥起不来 |
| 移动浏览器 + 篡改猴 | Edge 或 X 浏览器，脚本两个版本都给了 | `phone-browser` 不可用 |
| 宿主能执行 shell | 桥是本地进程，监听 `127.0.0.1:8765` | 同上 |

> `android-a11y-cli`、`android-clipboard`、`minis-scheduled` 是宿主 App（Minis）提供的命令。
> 换宿主（Termux / 桌面 DSH）需要自己实现等价的 CLI，否则只有 `phone-browser` 能跑。

## 路线 A：一键装

```bash
sh install.sh                 # 装到 /usr/local/bin
sh install.sh --bin ~/.local/bin --no-mcp
```

脚本做五件事：查 python3 → 把 `edge`/`mshot`/`mloc` 软链进 PATH → 起 8765 桥 → 注册 MCP `edge` → 自检。

## 路线 B：手动装

```bash
# 1. CLI 进 PATH
chmod +x skills/phone-browser/edge/edge skills/mobile-ops/scripts/{mshot,mloc}.py
ln -sf "$PWD/skills/phone-browser/edge/edge"     /usr/local/bin/edge
ln -sf "$PWD/skills/mobile-ops/scripts/mshot.py" /usr/local/bin/mshot
ln -sf "$PWD/skills/mobile-ops/scripts/mloc.py"  /usr/local/bin/mloc

# 2. 起桥
setsid python3 "$PWD/skills/phone-browser/edge/bridge.py" >/tmp/minis-bridge.log 2>&1 &
curl -s http://127.0.0.1:8765/status

# 3. 注册 MCP（stdio）
minis-mcp-cli add --name edge \
  --command python3 \
  --args "$PWD/skills/phone-browser/edge/mcp_edge.py" \
  --note "Edge 桥：在手机浏览器页面内执行 JS"
```

宿主用配置文件而不是 CLI 的，参照 `examples/mcp.edge.json`。

## 装完还要人工做两件事

1. **开无障碍**：设置 → 无障碍 → 本 App → 打开。验证：`android-a11y-cli service ping`。
2. **装油猴脚本**：手机浏览器访问 `http://127.0.0.1:8765/minis.user.js` 安装；**装好之前就开着的标签要刷新一次**，否则脚本不会注入。

## 验收

```bash
edge status                     # 有 tabs 列表 = 桥和海猴脚本都通了
edge js "document.title"        # 能返回当前页标题
mshot                           # 返回截图路径（Android ≤10）
```

`edge status` 空的三种原因：浏览器没开、脚本没装、Edge 在后台被冻结（见下）。

## 排错

| 现象 | 原因 | 处理 |
|---|---|---|
| `edge js` 返回 504 | 目标标签在后台，被系统冻结 | 让该页成为当前标签，或把"打开→操作→取结果"压进同一条命令 |
| `edge status` 没有 tabs | 油猴脚本没注入 | 刷新标签页；确认篡改猴对该站点启用 |
| 命令只打到不相干的标签 | 桥把任务投给了最近活跃的标签 | 只让一个标签在前台，或用 `url_contains` 限定 |
| `ACTION_SET_TEXT failed` | 目标是富文本/自绘控件 | 改走"写剪贴板 → 长按 → 粘贴"（见 `references/qqmail.md`） |
| `clipboard_requires_foreground` | 宿主不在前台拿不到剪贴板 | 把宿主切回前台再写 |
| 无障碍命令全超时 | 服务被系统强停 | 重新打开无障碍开关 |

## 卸载

```bash
rm -f /usr/local/bin/{edge,mshot,mloc}
pkill -f bridge.py
minis-mcp-cli remove --name edge    # 若宿主支持
```
