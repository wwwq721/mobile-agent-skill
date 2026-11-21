# 手机端 AI 操控技能包

让 AI 直接操作一台 Android 手机：读屏、点按钮、填表、开 App，以及在用户自己的浏览器里上网。
两个技能各自一个可执行脚本，Python 3 标准库，无第三方依赖。

| 技能 | 解决什么 | 入口 |
|---|---|---|
| `screen` | 操控任意 App 的原生界面：看一次、动一次、验一次 | `scr` |
| `x-browser` | 接管用户手机上的 X 浏览器（登录态/书签/历史都是他的） | `bw` |

```bash
scr look                      # 这一屏有什么
scr tap 设置                  # 找到→点中→等稳定→贴回新一屏
scr open 哔哩哔哩            # 启动 App（图标 → 文件夹 → 最近任务 → 全页扫）
scr do "open:设置" "tap:WLAN" # 一串动作一次做完

bw go https://example.com     # 开页并贴回正文（走真浏览器，带登录态）
bw read                       # 读当前屏
bw tap 登录                   # 点链接/按钮
bw close                      # 收尾：只关自己开的标签
```

## 设计取舍（值得抄的三条）

1. **看一次、动一次、验一次。** 每次动作都自带结果判定：`✔ … · 变` / `… · 无变化`。变了就往下走，不再复读屏幕——省的是模型的往返，不是脚本的 CPU。
2. **能用文字就别用坐标。** 坐标只在节点读不到的界面用；`sN`（上一次 look 的第 N 项）屏一变就作废，过期直接拒绝，不瞎点。
3. **登录态不可替换。** 浏览器不换容器、不代填密码；`bw fast` 走内置 WebView 只读公开页（毫秒级、不留标签），要真点真填才用 `bw go`。

## 装起来

前置：一台 Android 手机 + 能执行 shell 的宿主（本包按 Minis 提供的 `android-a11y-cli` 等命令编写）、python3 ≥ 3.7、X 浏览器（`com.mmbox.xbrowser`）。

```bash
sh install.sh      # 软链 scr / bw 到 /usr/local/bin，并做一次体检
```

手动步骤、验收命令、排错表见 [INSTALL.md](INSTALL.md)。

## 范围与边界

- **只有四件事**：打开、读取、点击、填普通表单。富文本编辑器（Lexical/Slate/ProseMirror 一类）不在范围内，工具会如实回失败，不假装成功。
- 无障碍通道**表达不了**"按住不动再拖"：手势时长按路径几何长度分配，"静止"长度是 0。桌面整理类操作因此受限，具体见 `skills/screen/scenarios/desktop.md`。
- 浏览器只有**最可见的那个标签**能执行 JS；后台标签会被系统冻结。
- 人和 AI 不要同时操作同一块屏幕：人在用时应当停手。

## 目录

```
skills/screen/        SKILL.md · scr · 迁移.md · references/{实测记录,设备参数}.md · scenarios/desktop.md
skills/x-browser/     SKILL.md · bw · reference.md · 迁移.md
```

`迁移.md` 是给"接手这个技能的人"的：第一次部署要注意什么、换机顺序、改哪块代码必须连带改什么。

## 许可

木兰宽松许可证第 2 版（Mulan PSL-2.0）。原创脚本与文档，不含第三方代码。
