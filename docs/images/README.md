# 图片来源与适用范围

本目录收录历次实际界面截图、2张原创软件流程SVG，以及1张明确标注无实机的驱动情景验证截图；2026-10-22新增2张手机操作界面截图。截图按日期命名，保留原始像素；未将历史页面或模拟画面标为当前实时状态。

| 文件 | 日期 | 内容 |
|---|---|---|
| [debug-console-20261021.png](debug-console-20261021.png) | 2026-10-21 | 本次六台续编完成后，页面提示6台已编号；校准尚未进行。 |
| [finger-training-20261015.png](finger-training-20261015.png) | 2026-10-15 | 历史实机开发中的五指反馈、范围与姿态轴。 |
| [score-follow-20261015.png](score-follow-20261015.png) | 2026-10-15 | 历史原谱跟随界面，截图时已停止；不表示当前装置正在运动。 |
| [score-review-20261014.jpg](score-review-20261014.jpg) | 2026-10-14 | 历史PDF逐项指法、时值校对界面。 |
| [read-score-central-do-20261015.png](read-score-central-do-20261015.png) | 2026-10-15 | 读谱教程：两个黑键与中央Do。 |
| [read-score-note-key-20261015.png](read-score-note-key-20261015.png) | 2026-10-15 | 读谱教程：中央Do与谱中音符。 |
| [read-score-mobile-20261015.png](read-score-mobile-20261015.png) | 2026-10-15 | 读谱教程在390px窄屏下的截图。 |
| [workflow-20261021.svg](workflow-20261021.svg) | 2026-10-21 | 原创使用流程说明，不是实物照片或测试报告。 |
| [enrollment-resume-20261021.svg](enrollment-resume-20261021.svg) | 2026-10-21 | 原创续编过程说明，不是运动或穿戴验收。 |

| [usb-driver-scenario-20261021.png](usb-driver-scenario-20261021.png) | 2026-10-21 | 一键安装驱动的隔离浏览器情景；不是真实客户驱动安装验收。 |

本机原始串口日志、校准与固件备份没有随图片上传。教程为本项目自绘界面；原谱校对截图仅用于说明软件功能，仓库未新增完整PDF语料。

2026-10-22新增：

| 文件 | 内容与范围 |
|---|---|
| [mobile-speed-20261022.png](mobile-speed-20261022.png) | 手机尺寸浏览器中的速度精调面板，处于待机；不是手机穿戴演奏验收。 |
| [mobile-upload-20261022.png](mobile-upload-20261022.png) | 实际网页上传带原谱包到临时位置100，显示上传及原谱保存成功；回读核对后已删除该测试副本。 |

2026-11-02 新增（漫画风改版，分支 `rewrite/comic-ui`）：

| 文件 | 内容与范围 |
|---|---|
| [comic-home-20261102.png](comic-home-20261102.png) | 「开始」页与小音入门气泡。 |
| [comic-training-20261102.png](comic-training-20261102.png) | 手指训练页，五指统一配色，待机中。 |
| [comic-library-20261102.png](comic-library-20261102.png) | 曲库页与内置曲谱。 |
| [comic-review-20261102.png](comic-review-20261102.png) | PDF 识谱校对：整行指法对照与放大镜，内置原谱「第6首」。 |

以上 4 张由 `tools/dev/dev_preview.py` 在浏览器中按 1280×800 截取，界面与 EXE 同源；连接的是 `tools/dev/sim_glove.py` 模拟手套（顶栏显示 `socket://127.0.0.1`），不是实机运动截图。
