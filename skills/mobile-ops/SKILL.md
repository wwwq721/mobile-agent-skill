---
name: mobile-ops
description: 操作本机安卓界面时使用（点击、滑动、读屏、找元素、截图看屏幕、批量点按）。提供少往返的操作顺序、节点定位、两种授权错误的区分，以及 mshot / mloc 两个封装。凡涉及"帮我点/打开/看看屏幕上有什么/交给你操作"都先加载本技能。
version: 1.8.4
---
# 手机操控

用更少的上下文和模型往返，把操作做准。

**前提：用户自己操作手机时会把无障碍关掉**，那时这套工具根本跑不起来。
所以不需要检测"用户是否正在操作"，也不存在"用户同时截图"——相关防御一律不做。

**真正的耗时不是命令执行，是模型看图、理解界面、再决定下一步的轮次。**
设备侧几百毫秒的查询，在同一次脚本里完成就是划算的。

## 操作顺序

- 有可靠的直达入口（`android-open` / deep link）就用；否则先 `android-a11y-cli ui dump --compact` 取结构，在脚本里筛目标，只输出必要节点和结论。
- 优先 `tap node <id>` / `tap text <文本>`；没有可用节点才用当前布局的坐标；结构不足才截图。
- 节点编号只属于当次快照，**不能存起来长期复用**。
- 同屏已知步骤放在一次工具调用里完成。换页或重绘后，在同一个脚本里重新读取、定位再继续——省的是模型往返，不是省掉必须的状态读取。
- 验证用一次实际 dump 里的目标节点或预期结果。`ui info` 的包名可能是残留旧窗口，不能作为成功的唯一依据。
- 等元素出现/消失用 `wait appear|disappear|stable`，别 sleep；不确定当前有没有弹窗先 `dialog detect`。
- 失败先看返回的错误码，不重复盲点；换层，不在同一层重试第三次。

## 常用入口

`mloc learn <名字> --desc <描述>` 记住入口，`mloc tap <名字>` 校验归属后点击。

只记固定语义的入口（桌面图标、底部 tab、设置项），存选择器不存 nodeId。
展开/折叠、提交后消失的按钮别记——点完界面就变，记了必然 stale。
**匹配不唯一时不点**：返回 `ambiguous`，用 `--desc` 收紧，或重新 dump 定位。

`unknown_package` 且 dump 拿不到节点 = 无障碍/授权没起来，**不是库坏了**，先查那两件事；
`tap` 报 `STALE_NODE` 就重 dump 重定位，别复用旧 id。其余错误码见 `references/glitches.md`。

需要看像素时：Android 11+ 直接 `android-a11y-cli ui screenshot`；
Android 10 及以下用 `mshot`，输出图片路径（失败排查见 `references/glitches.md`）。

## 报错先分清两件事

| 错误码 | 含义 | 怎么办 |
|---|---|---|
| `SERVICE_NOT_RUNNING` | 系统无障碍没开或没绑定 | 设置→辅助功能→无障碍：关→退一级→再进→开；只点开一次可能不重新绑定 |
| `PERMISSION_DENIED` | Minis 的 Agent 授权拦截 | Minis 设置→权限→Integrations→Accessibility，改成 Allow 或 Ask |

`service status` / `service ping` **不经**这道授权检查，所以即使报 `running:true`，操作仍可能被拒。
**不要说成"无障碍没开"**——用户开的是系统开关，这里要的是 App 内的 Agent 授权。

## 按需参考

- QQ 邮箱 → `references/qqmail.md`
- X 浏览器界面 → `references/xbrowser.md`
- 排查命令与定位失败 → `references/glitches.md`
- 导出、换机、截图参数 → `MIGRATION.md`

## 相册

`mshot` 把图导出到 `/var/minis/workspace/shots/mshot/`（私有目录，只留最近 5 张），
导出成功后删相册原件。认领规则：`id` 比基线新 + 文件名像系统截图；
出现多张时取最新一张（这个窗口里只可能是本次点击产生的）。
等不到新图就明确失败，一张不删。**绝不批量删相册**——
MediaStore 删除是永久的，荣耀图库没有可用回收站。
