# -*- coding: utf-8 -*-
"""线程间通信总线：UI 与后台 worker / 全局钩子共用。"""

import queue

cmd_q = queue.Queue()       # UI -> worker：下发控制命令
result_q = queue.Queue()    # worker -> UI：回传执行结果
capture_q = queue.Queue()   # 钩子 -> UI：捕获到的鼠标按键

# 连接状态：只有用户点击「连接」并成功后才置为 True，未连接时所有控制操作冻结
CONNECTED = {"ok": False}
