# 火焰图性能分析工具

本目录包含用于生成火焰图的自动化工具，支持同时记录CPU和内存分配。

## 文件说明

1. `flamegraph_profiler.py` - 单个可执行文件的通用分析器
2. `run_profiling.py` - 针对两个预设项目(liii/mogan, mogan)的分析器
3. `generic_profiler.py` - 基于配置文件的通用分析器（推荐）
4. `projects.yaml` - 项目配置文件

## 快速开始

### 1. 安装依赖
- dtrace (macOS系统自带)
- FlameGraph工具集 (已安装在 `/Users/yuki/git/FlameGraph`)
- Python 3.6+

### 2. 使用通用分析器（推荐）

```bash
# 进入目录
cd /Users/yuki/git/fireimage

# 分析所有项目（默认30秒采样）
python3 generic_profiler.py

# 分析特定项目
python3 generic_profiler.py --project liii
python3 generic_profiler.py --project mogan

# 自定义采样时间
python3 generic_profiler.py --time 60

# 仅构建不分析
python3 generic_profiler.py --build-only

# 不构建，仅分析
python3 generic_profiler.py --no-build

# 禁用内存分析
python3 generic_profiler.py --no-memory
```

### 3. 使用单个项目分析器

```bash
# 分析特定可执行文件
python3 flamegraph_profiler.py --executable /path/to/program

# 更多选项
python3 flamegraph_profiler.py --executable /path/to/program --time 60 --output ./profiles
```

## 项目配置

配置文件 `projects.yaml` 定义了要分析的项目。可以轻松添加新项目：

```yaml
# 添加新项目
myproject:
  path: "/path/to/your/project"
  output_dir: "/path/to/output"
  build_cmds:
    - "./configure"
    - "make"
  executable: "myapp"  # 可执行文件名称
  target: ""           # 构建目标（如适用）
  args: []             # 启动参数
  env: {}              # 环境变量
  startup_delay: 3     # 启动后等待时间（秒）
```

## 输出文件

分析完成后，输出目录将包含：
- `cpu.svg` - CPU火焰图
- `memory.svg` - 内存分配火焰图（如果启用）
- `cpu.stacks`, `memory.stacks` - 原始堆栈数据
- `cpu.folded`, `memory.folded` - 折叠后的堆栈数据
- `profiling.log` - 分析日志

## 火焰图查看

在浏览器中打开SVG文件查看火焰图：
- 点击任何部分可以放大
- 使用Ctrl+F搜索函数名
- 使用右上角的控件调整显示

## 注意事项

1. 需要sudo权限运行dtrace
2. 分析过程中会启动目标程序并附加dtrace
3. 分析完成后会自动终止目标程序
4. 如果程序需要用户交互，可能影响分析结果

## 故障排除

1. **找不到可执行文件**：检查`executable`配置项，确保项目已构建
2. **dtrace权限问题**：需要sudo权限，可能会提示输入密码
3. **程序过早退出**：调整`startup_delay`参数
4. **火焰图生成失败**：检查FlameGraph目录路径是否正确

## 添加新项目

1. 编辑`projects.yaml`文件，添加新项目配置
2. 运行`python3 generic_profiler.py --project 项目名`进行测试
3. 根据需要调整配置参数