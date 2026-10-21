# 软件网页实际点击记录

> 公开说明：本文保留原验证时点的历史事实与未验证项。原始设备日志、Flash 备份、客户运行包和本地验证记录未随仓库打包；下文的记录目录及文件名用于追溯，不是本仓库的下载链接。当前功能入口以仓库首页为准。

本轮只测试电脑USB；热点按用户要求不测。用户已确认手套摘下、电脑能正常放音。新增页面源码仅精简文字与清除旧错误，没有更改方向、运动参数、校准范围或设备协议。

## 已完成

- 五指卡片保留指名、动作、水位、实时值、一行校准范围；完整允许上下限在范围提示中。越界、未知及过期仍默认显示。正常状态不再重复写“当前位置”。
- 真实点击拇指按下和抬起，网页按压状态与舵机反馈变化；点击声音关闭、重新开启及停止。
- 最终页面上真实点击最快逐指、组合、交替各一轮，三个按钮流程均返回“已停止：已完成”。不是用HTTP替代这些点击。
- 真实点击波尔卡原谱节选“开始训练”，页面进入演奏中，设备最终为7/7音符、completed、inactive。
- 用户手动恢复后台后，真实点击阿拉伯风、南瓜布吉舞“开始训练”，页面均进入演奏中；各自最终10/10、6/6音符、completed、inactive。三首网页实际点击已齐。
- 实际复现小指卸力后2635超过允许上限2601。正常模式拒绝下一次启动，页面默认红字显示具体阈值，截图保留。随后按已确认的摘下状态设置已有OFFHAND台架回位模式继续，允许范围没有扩大。
- 发现旧红错误在成功重试后仍残留，以及训练完成提示写成曲谱结束；修正后真实前端源码行为回归66/66通过。过期请求不会清除后续的新错误。

最终JS SHA256：`be058f49ba97cb5e734aa9a03fc12fc2343bce16897dfa6142cdb34f65a90616`。

## 声音证据与未完成项

真实浏览器WebAudio上下文由suspended变为running，Oscillator、Gain连接到AudioDestination，实时音频时钟持续推进；关闭／停止后旧节点释放。这证明网页音频链路启动，不能代替扬声器实测。

系统最初没有可枚举输出，随后出现“耳机(DAU Audio)”。2秒基线、8秒及恢复后3秒拇指长音WASAPI loopback均没有收到实际数据包，报告analysis=null，未生成假WAV或假RMS。浏览器启动参数没有mute-audio等标志。本采集路径未取到流，不能据此否定用户听感，也不能给出声学延迟或波形测量结论。

用户已对本次网页拇指试音明确回复“能听到持续的音”，对两段曲谱回复“正常，结束后安静”。本轮持续音、曲谱联动和结束静音有现场确认；独立关声／重新开声开关已实际点击，但用户没有单独确认这组开关听感。以前三首接口回归与本轮网页点击证据分别保留。

## 后台中断

用户再次要求继续后，内置浏览器连接已重建，8123无监听，未检测到bridge.py进程，网页返回ERR_CONNECTION_REFUSED。恢复后台的已验证路径Start-Process请求被自动审批拒绝，原工具只给出`blocked by policy`，没有更具体原因。没有用其他工具、CLI或UI代启动绕过拒绝。

已准备供用户手动启动的`本地测试启动脚本：启动软件测试台.bat（未随仓库打包）`：使用当时本机已安装的 Python，运行项目host/bridge.py、8123、no-auto；不恢复旧目标、不自动连接、不烧录。用户回复“已启动”后，实际核验8123健康、COM3连接、六台贵版位置反馈有效，再继续网页实操。全部结束后实际点击停止并恢复NORMAL，最后active=false；没有代用户绕过启动拒绝。

客户r3归档仍为上一轮39b33版本网页与已实机验证固件；本轮最新精简页面在源码／本地服务目录，未声称旧ZIP包含本轮新文字。

## 证据目录

`本地验证记录：software-ui-20261011/`：

- `thumb-down-compact.jpg`、`training-complete-compact.jpg`、`polka-playing-compact.jpg`：实际页面截图。
- `real-outside-limit-compact.jpg`、`offhand-setup.json`：真实越界与摘下回位测试模式。
- `polka-ui-final-state.json`：真实7/7完成状态。
- `arabesque-ui-final-state.json`、`pumpkin-ui-final-state.json`：真实10/10、6/6完成状态。
- `arabesque-playing-resumed.jpg`、`pumpkin-playing-resumed.jpg`、`final-compact-page.jpg`：恢复后实际页面截图。
- `resumed-audio-listening.json`、`resumed-final-serial-trace.json`：现场听感、停止、NORMAL恢复及真实串口记录。
- `actual-device-samples.json`、`actual-serial-trace.json`：前段只读观察记录。
- `baseline-no-output-1.json`、`baseline-headphone-1.json`、`thumb-audio-20261011-115553-7830.json`：真实音频采集失败保留。
- `audio-session-probe.json`、`browser-audio-flags.json`、`audio-sessions.json`：只读输出／会话调查。
