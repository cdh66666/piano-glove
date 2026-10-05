# 两副手套同时调试

接好两个主控 USB 后，运行 `host/start-dual.bat`。只有恰好两个 CP210x 主控时才自动选择；否则在命令行指定：

```bat
host\start-dual.bat COM3 COM27
```

第一个串口使用 `http://127.0.0.1:8123/web_piano_glove.html?simple=1`，第二个使用 `http://127.0.0.1:8124/web_piano_glove.html?simple=1`。页面根据各自主控的实时反馈显示 SC09 或 STS 型号，COM 顺序不代表舵机型号。

两个调试台各自固定串口；拔下一副后只等待它重连，不接管另一副。页面不能切换固定串口，连接与烧录接口也拒绝其他串口。重新连接不会自动恢复动作。

校准全过程文件分别保存在 `host/calibration_recordings/COM3`、`host/calibration_recordings/COM27`。未完成的校准仅保留在各自页面会话内，不根据相同的设备 AP 名恢复另一副的数据。已有运行中的端口若不属于指定串口，启动器会报错，不会关闭进程。

此启动器只枚举电脑 USB 串口并启动调试台，不发送修改舵机 ID 的命令。不要同时用旧单机启动器打开第三个桥去抢占这两个串口。
