# QQ 邮箱写信

只在要发邮件时加载。以下坐标是 2026-11-03 在 1080×2400 上实测，
App 改版后会变——优先按文字 dump 定位，坐标只作兜底。

**最快路径是 mailto intent，不是点界面**——收件人/主题/正文一次性预填，一步到位：

```bash
python3 -c "import urllib.parse as u;print('mailto:a@b.cn?subject=%s&body=%s'%(u.quote('主题'),u.quote(open('/tmp/body.txt').read())))" > /tmp/m.txt
android-open "$(cat /tmp/m.txt)"      # 弹出选择器
# 选「通过邮件发送」(836,2115) → 「仅此一次」(311,2268) → 落到 QQ 邮箱写信页
```

启动 App 本身：`android-open 'intent:#Intent;package=com.tencent.androidqqmail;end'`（android-open 走系统默认浏览器，**必须带 package**）。

手点路径（坐标 1080×2400）：首页右上「写邮件和设置等功能」(978,183) → 「写邮件」(744,366) → 窗口出现。
写信页按钮：`取消`(125,248) · `发送`(955,248) · 收件人(508,391) · 主题(618,667) · 正文(540,898) · 底部工具栏 `附件`(77,1539) `已读回执`(231,1539) `定时邮件`(386,1539) `富文本`(848,1539)。
键盘 ⌫ 在 (1034,2072)；退出确认弹窗按钮 `取消`(462,1432) `保存草稿`(666,1432) `离开`(870,1432)。

**坑**：
- **正文富文本框不吃 `input text`**（`ACTION_SET_TEXT failed`）：收件人/主题是普通 EditText，`input text` 可用；正文只能粘贴。
- **正文要换行，走剪贴板粘贴**（2026-11-03 实测可用，唯一能保住换行的路径）：
  1. **Minis 在前台**时 `android-clipboard set "$(cat /tmp/body.txt)"`（App 不在前台会报 `clipboard_requires_foreground`；用多任务卡片切回 Minis，`intent:package=com.openminis.app` 拉不回来）；
  2. 切到 QQ 邮箱，点正文 → `tap xy 540 898 --long`（长按，返回里仍写 `action: tap`，但确实长按了）→ 弹「粘贴 (126,292) / 全选 (282,292)」→ 点粘贴；
  3. 验证：`ui dump` 里正文节点文本应含 `\n`。粘贴保留空行，段落正常。
- **mailto 的 `\n`、`\r\n` 都会被压成空格** → 用 mailto 预填正文只适合「一句话」场景；长正文要换行就别用 mailto，直接剪贴板。
- 剪贴板内容会被用户随后的复制覆盖，粘贴前先确认正文是不是自己的（dump 一下开头）。
- 偶尔正文首字符会多出一个「，」（预填与旧草稿叠加时出现），用「点开头 → 点 ⌫」删掉：先 `tap xy 100 800` 让细竖光标落在「，」右侧，再点 ⌫。
- 邮件正文有长度上限风险：mailto URL 约 6 KB 正常，别无限加长。
- **草稿箱入口难找**：首页 → 账号(422,1374) → 进收件箱；点顶部账号名(510,159) 只弹账号切换抽屉，没有文件夹树。发信前别指望靠草稿箱找回过内容，尽量一次填完就发。

## 定位优先

坐标只作兜底。找控件用：

```bash
android-a11y-cli ui dump --compact | jq -r '.data.nodes[] | select(.text) | "\(.nodeId)\t\(.text)\t\(.center.x),\(.center.y)"'
```

`tap node <id>` 不依赖分辨率，也不怕改版。
