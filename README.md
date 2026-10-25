# Music adb

一款使用 **adb** 连接手机，让电脑也能控制手机音乐流媒体播放的工具。

连接手机后，可以用鼠标侧键切歌、用滑杆或滚轮调音量，无需把手从键盘上移开；界面基于 PyQt5 + PyQt-Fluent-Widgets，支持跟随系统的深色 / 浅色主题。

## 功能

- **切歌**：上一曲 / 下一曲 / 播放暂停 / 停止，通过 `cmd media_session dispatch` 下发
- **按键录制绑定**：点击「设置上一曲 / 设置下一曲」，按下任意鼠标按键（侧键 / 中键 / 右键）或键盘按键（可带 `Ctrl` / `Alt` / `Shift` 组合）即可完成绑定
- **系统媒体键通道**：鼠标驱动把侧键设为「上一曲 / 下一曲」时，程序会直接接收系统媒体键，无需绑定，可与录制的按键同时生效
- **音量调节**：滑杆拖动或鼠标滚轮（5 一档）下发，静默调节，手机不会弹出音量条；支持静音 / 取消静音与重新读取
- **连接管理**：USB 直连或 WiFi（`adb tcpip 5555` + `IP:5555`），自动检测设备；未连接时所有控件与按键均被冻结，避免误操作
- **可复制的运行日志**：报错信息一键复制，便于排查
- **界面**：Fluent 风格 5 页式布局，深色 / 浅色主题可固定，标题栏按钮随主题自动适配

## 界面截图

### 连接设备

![连接设备](run_photo/01-connect.png)

### 播放控制

![播放控制](run_photo/02-playback.png)

### 音量

![音量](run_photo/03-volume.png)

### 运行日志

![运行日志](run_photo/04-log.png)

### 设置

![设置](run_photo/05-settings.png)

## 下载

前往 [Releases](../../releases) 下载最新的 `PhoneMusicController.exe`，双击即可运行，无需安装 Python 环境。

## 使用步骤

1. 手机开启「开发者选项 → USB 调试」，用数据线连接电脑（首次连接需在手机上确认授权）
2. WiFi 连接时，先在手机执行 `adb tcpip 5555`，再在「设备地址」填写 `手机IP:5555`
3. 点击「连接」，状态变绿后即可使用侧键切歌与音量控制
4. 需要改键时，在「播放控制」页点击「设置上一曲 / 设置下一曲」，按下目标按键即可（`Esc` 或「取消」退出录制）

> Windows 上首次运行如遇 SmartScreen 提示，选择「更多信息 → 仍要运行」即可。

## 工作原理

| 功能 | 实现 |
| --- | --- |
| 切歌 | `adb shell cmd media_session dispatch next / previous / play-pause / stop` |
| 音量 | `adb shell cmd audio adj-volume 3 RAISE / LOWER`、`MUTE / UNMUTE`，绝对值按差值分档下发并回读收敛 |
| 按键捕获 | Win32 低级钩子 `WH_MOUSE_LL` / `WH_KEYBOARD_LL`（与安装钩子的线程共用消息循环） |
| 免闪窗 | 所有 adb 调用使用 `CREATE_NO_WINDOW` |

> 说明：部分系统（如 HyperOS）会拒绝 `input keyevent`，提示 `INJECT_EVENTS permission`，因此这里统一走 `media_session` 与 `audio` 命令通道。

## 从源码运行

```bash
pip install PyQt5 PyQt-Fluent-Widgets
python phone_music_controller.py
```

## 打包

```bash
pyinstaller PhoneMusicController.spec --distpath dist --workpath build --noconfirm
```

## 目录结构

```
PhoneMusicController/
├── main.py                    # 入口：高 DPI、配置、后台线程、全局钩子、主窗口
├── phone_music_controller.py  # 兼容旧入口，转调 main.main
├── app/
│   ├── config.py              # 配置读写、按键绑定解析与显示
│   ├── adb.py                 # adb 查找与命令下发
│   ├── bus.py                 # 线程间队列与连接状态
│   ├── worker.py              # adb 串行执行线程
│   ├── input_hooks.py         # 鼠标 / 键盘低级钩子、媒体键与按键录制
│   └── ui/                    # 主窗口与五个页面
├── tests/test_core.py         # 核心逻辑单元测试
├── legacy/                    # 迁移前的 Tkinter 版本备份
└── run_photo/                 # 运行界面截图
```

## 已知限制

- 录制的键盘按键会被程序独占（不再输入到其它窗口），建议使用 `F1`~`F12` 或 `Ctrl` / `Alt` 组合键
- 「拦截已绑定的鼠标按键」「拦截媒体键」默认关闭，开启后会独占这些按键，避免被浏览器或其它音乐软件同时响应

## License

[MIT](LICENSE)
