# Instruments 使用指南

## 1. 目的
- 利用 Apple Instruments 的 Allocations/Leaks/Time Profiler 模板，结合当前报告定位内存分配/释放的痕迹，验证是否存在真正的内存泄漏或频繁 malloc/free。
- 指定 Mogan 可执行文件，记录运行期间活跃对象、retained paths 以及泄漏堆栈轨迹。

## 2. 运行前准备
1. 确保项目使用 Debug（保留符号）或 Instrument 专用配置构建；可以通过 `run_analysis.sh` 调用 `qmake`/`cmake` 后再 `ninja`/`make` 生成 `Mogan` 可执行文件。
2. 关闭过度优化（-O0/-g）以便 Instruments 能看到详细调用。
3. 若需要 `malloc_history`，可在终端前缀 `MallocStackLogging=1 ./Mogan`（该环境变量也可写入 Instruments Scheme 里的 Run 配置）

## 3. Instruments 录制步骤
1. 打开 Xcode，选择 Xcode > Open Developer Tool > Instruments；或在 Spotlight 里搜索 Instruments。
2. 模板选择：
	- **Allocations + Leaks**：同时追踪内存分配、实时泄漏、堆栈。
	- **Time Profiler**：辅助判别是哪里发生大量 malloc/free，或 CPU 耗时热点。
3. 设置 Target：点击右上角 Target 下拉菜单，选择你的 `Mogan` 可执行文件（如果已在终端运行，则选 Attach to Process 并选择对应 PID）。
4. 点击红点开始采集，期间正常使用 Mogan 的典型流程（打开文档、排版、关闭窗口等），尽量模拟漏报场景。

## 4. 分析关键视图
1. **Allocations**：观察“Live Bytes”和“# Persistent Objects”的曲线是否持续上升。对比多个快照（右上角 + 按钮）来确认哪些类或函数保留的对象越来越多。
2. **Leaks**：查看 Leaks 面板，双击条目展开调用栈；重点追踪 `MallocStack` 指向的源函数。
3. **Call Tree**：过滤显示 `malloc`/`free` 相关函数，看哪些路径频繁触发分配；配合“Invert Call Tree”可定位底层泄漏源。
4. 如果释放次数非常少，可以在 Allocations 界面右键勾选“Record Reference Counts”和“Track Persistent Allocation Info”获取更多对象生命周期信息。

## 5. 进阶调试
1. **MallocStackLogging=1**：在 Instruments Terminal Scheme 中设置环境变量或手工运行，之后可以用 `leaks <pid>`/`malloc_history <pid> <address>` 查看某块地址是否释放。
2. **Attach to Running Process**：如果 `run_analysis.sh` 会启动 Mogan（或测试脚本），先运行脚本，然后在 Instruments 选择“Attach to Process”，这样无需在 Instruments 内重新启动。
3. **导出 trace**：完成后点击 File > Export Trace 保存 `.trace` 文件，可附加到 issue 或未来复查。

## 6. 结合报告的提醒
- 如果 leak/alloc 比例极低而内存持续升高，先确认 Instruments 是否真的看到释放；若 Leaks 面板为空但 Live Bytes 仍在增长，说明对象可能因为引用未断开而被保留（检查持有者）。
- 与 `analysis_report.md` 中的热点函数（比如 `bridge_rep::typeset`、`QWidget` 绘制路径等）配合，针对它们的调用栈设置符号断点或手动标记快照。

## 7. 小贴士
- 录制前清理已有的 Instruments 数据：File > New 来确保没有残留的快照。
- 若想自动重现特定场景，可以在终端写个脚本控制 Mogan 执行常规任务，再用 Instruments Attach。
- Instruments 输出的堆栈可以右键复制路径，记下对应源码文件/行号用于后续修复。
