#!/usr/bin/env python3
"""
通用火焰图性能分析脚本
支持同时记录CPU和内存分配，生成火焰图

依赖：
1. dtrace (macOS系统自带)
2. FlameGraph工具集 (https://github.com/brendangregg/FlameGraph)
   需要将FlameGraph目录添加到PATH或设置FLAMEGRAPH_DIR环境变量

用法：
    python3 flamegraph_profiler.py --executable /path/to/program [参数]
"""

import os
import sys
import time
import subprocess
import argparse
import tempfile
import signal
import threading
import atexit
from pathlib import Path

# 默认配置
DEFAULT_SAMPLE_TIME = 30  # 秒
DEFAULT_CPU_FREQ = 99     # Hz
DEFAULT_MEMORY_SAMPLE = True
FLAMEGRAPH_DIR = os.environ.get('FLAMEGRAPH_DIR', '/Users/yuki/git/FlameGraph')

class FlamegraphProfiler:
    def __init__(self, executable, output_dir=None, sample_time=DEFAULT_SAMPLE_TIME,
                 cpu_freq=DEFAULT_CPU_FREQ, enable_memory=True):
        self.executable = Path(executable).resolve()
        self.sample_time = sample_time
        self.cpu_freq = cpu_freq
        self.enable_memory = enable_memory

        # 设置输出目录
        if output_dir:
            self.output_dir = Path(output_dir).resolve()
        else:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            self.output_dir = Path.cwd() / f"flamegraph_{timestamp}"

        # 确保输出目录存在
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 检查FlameGraph工具
        self.flamegraph_dir = Path(FLAMEGRAPH_DIR)
        if not self.flamegraph_dir.exists():
            raise FileNotFoundError(f"FlameGraph目录不存在: {self.flamegraph_dir}")

        # 进程引用
        self.target_process = None
        self.dtrace_processes = []

        # 文件路径
        self.cpu_stacks = self.output_dir / "cpu.stacks"
        self.cpu_folded = self.output_dir / "cpu.folded"
        self.cpu_svg = self.output_dir / "cpu.svg"

        self.mem_stacks = self.output_dir / "memory.stacks"
        self.mem_folded = self.output_dir / "memory.folded"
        self.mem_svg = self.output_dir / "memory.svg"

        print(f"分析配置:")
        print(f"  可执行文件: {self.executable}")
        print(f"  采样时间: {self.sample_time}秒")
        print(f"  CPU采样频率: {self.cpu_freq} Hz")
        print(f"  内存分析: {'启用' if enable_memory else '禁用'}")
        print(f"  输出目录: {self.output_dir}")
        print(f"  FlameGraph目录: {self.flamegraph_dir}")

    def check_prerequisites(self):
        """检查必要的工具是否可用"""
        # 检查dtrace
        try:
            subprocess.run(['which', 'dtrace'], check=True, capture_output=True)
        except subprocess.CalledProcessError:
            raise RuntimeError("dtrace工具不可用，请确保已安装")

        # 检查FlameGraph脚本
        required_scripts = ['stackcollapse.pl', 'flamegraph.pl']
        for script in required_scripts:
            script_path = self.flamegraph_dir / script
            if not script_path.exists():
                raise FileNotFoundError(f"FlameGraph脚本不存在: {script_path}")

        # 检查可执行文件
        if not self.executable.exists():
            raise FileNotFoundError(f"可执行文件不存在: {self.executable}")
        if not os.access(self.executable, os.X_OK):
            raise PermissionError(f"可执行文件没有执行权限: {self.executable}")

        print("✓ 所有依赖检查通过")

    def generate_dtrace_cpu_script(self):
        """生成CPU分析的dtrace脚本"""
        script = f"""
#pragma D option quiet
#pragma D option stackframes=100
#pragma D option ustackframes=100
#pragma D option defaultargs

profile-{self.cpu_freq}
/pid == $target/
{{
    @[ustack()] = count();
}}

tick-{self.sample_time}s
{{
    exit(0);
}}
"""
        return script

    def generate_dtrace_memory_script(self):
        """生成内存分析的dtrace脚本"""
        script = f"""
#pragma D option quiet
#pragma D option stackframes=100
#pragma D option ustackframes=100
#pragma D option defaultargs

pid$target::malloc:entry
{{
    @alloc[ustack()] = sum(arg0);
    @count[ustack()] = count();
}}

pid$target::free:entry
{{
    @free[ustack()] = count();
}}

tick-{self.sample_time}s
{{
    printf("\\n=== 内存分配统计 (字节) ===\\n");
    printa(@alloc);

    printf("\\n=== 内存分配次数 ===\\n");
    printa(@count);

    printf("\\n=== 内存释放次数 ===\\n");
    printa(@free);

    exit(0);
}}
"""
        return script

    def run_target_process(self):
        """启动目标进程"""
        print(f"启动目标进程: {self.executable}")
        self.target_process = subprocess.Popen(
            [str(self.executable)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid  # 创建新的进程组
        )

        # 等待进程完全启动
        time.sleep(2)

        if self.target_process.poll() is not None:
            stderr = self.target_process.stderr.read().decode('utf-8', errors='ignore')
            raise RuntimeError(f"目标进程过早退出: {stderr}")

        print(f"✓ 目标进程已启动 (PID: {self.target_process.pid})")
        return self.target_process.pid

    def run_dtrace_script(self, script_content, output_file, description):
        """运行dtrace脚本并捕获输出"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.d', delete=False) as f:
            f.write(script_content)
            dtrace_script = f.name

        try:
            print(f"开始{description}...")
            cmd = ['sudo', 'dtrace', '-x', 'ustackframes=100', '-n', script_content, '-o', str(output_file)]

            # 注意：这里使用了简化的方式，实际可能需要根据目标PID调整
            # 对于内存分析，需要pid$target语法，这需要在命令行中指定PID
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            self.dtrace_processes.append(process)

            # 等待dtrace进程完成
            process.wait(timeout=self.sample_time + 5)

            if process.returncode != 0:
                stderr = process.stderr.read()
                print(f"警告: {description} dtrace脚本返回非零代码: {process.returncode}")
                print(f"错误输出: {stderr[:500]}")

            print(f"✓ {description}完成")

        except subprocess.TimeoutExpired:
            print(f"警告: {description} dtrace脚本超时")
            process.terminate()
        except Exception as e:
            print(f"错误: {description} dtrace脚本执行失败: {e}")
        finally:
            # 清理临时文件
            try:
                os.unlink(dtrace_script)
            except:
                pass

    def generate_flamegraph(self, input_file, output_svg, title, script_type="cpu"):
        """生成火焰图"""
        if not input_file.exists() or input_file.stat().st_size == 0:
            print(f"警告: {input_file} 不存在或为空，跳过生成火焰图")
            return False

        try:
            # 折叠堆栈
            if script_type == "cpu":
                collapse_script = self.flamegraph_dir / "stackcollapse.pl"
            else:
                # 内存分析可能需要不同的折叠脚本
                collapse_script = self.flamegraph_dir / "stackcollapse.pl"

            # 首先折叠数据
            with open(self.cpu_folded if script_type == "cpu" else self.mem_folded, 'w') as outfile:
                subprocess.run(
                    [str(collapse_script), str(input_file)],
                    stdout=outfile,
                    stderr=subprocess.PIPE,
                    check=True
                )

            # 生成SVG火焰图
            flamegraph_script = self.flamegraph_dir / "flamegraph.pl"
            with open(output_svg, 'w') as outfile:
                subprocess.run(
                    [str(flamegraph_script), f'--title={title}',
                     str(self.cpu_folded if script_type == "cpu" else self.mem_folded)],
                    stdout=outfile,
                    stderr=subprocess.PIPE,
                    check=True
                )

            print(f"✓ 生成火焰图: {output_svg}")
            return True

        except subprocess.CalledProcessError as e:
            print(f"错误: 生成火焰图失败: {e}")
            if e.stderr:
                print(f"错误输出: {e.stderr.decode('utf-8', errors='ignore')}")
            return False

    def cleanup(self):
        """清理资源"""
        print("\n清理资源...")

        # 终止dtrace进程
        for proc in self.dtrace_processes:
            if proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except:
                    pass

        # 终止目标进程
        if self.target_process and self.target_process.poll() is None:
            try:
                os.killpg(os.getpgid(self.target_process.pid), signal.SIGTERM)
                self.target_process.wait(timeout=2)
            except:
                try:
                    self.target_process.terminate()
                    self.target_process.wait(timeout=1)
                except:
                    pass

        print("✓ 清理完成")

    def run(self):
        """运行完整的性能分析流程"""
        try:
            # 1. 检查依赖
            self.check_prerequisites()

            # 2. 启动目标进程
            target_pid = self.run_target_process()

            # 注册清理函数
            atexit.register(self.cleanup)

            # 3. 生成并运行dtrace脚本
            print("\n开始性能分析...")

            # CPU分析
            cpu_script = self.generate_dtrace_cpu_script()
            cpu_script = cpu_script.replace('$target', str(target_pid))
            self.run_dtrace_script(cpu_script, self.cpu_stacks, "CPU分析")

            # 内存分析（如果启用）
            if self.enable_memory:
                mem_script = self.generate_dtrace_memory_script()
                mem_script = mem_script.replace('$target', str(target_pid))
                self.run_dtrace_script(mem_script, self.mem_stacks, "内存分析")

            # 4. 生成火焰图
            print("\n生成火焰图...")

            # CPU火焰图
            if self.cpu_stacks.exists() and self.cpu_stacks.stat().st_size > 0:
                self.generate_flamegraph(
                    self.cpu_stacks, self.cpu_svg,
                    f"CPU火焰图 - {self.executable.name} ({self.sample_time}s)",
                    "cpu"
                )

            # 内存火焰图
            if self.enable_memory and self.mem_stacks.exists() and self.mem_stacks.stat().st_size > 0:
                self.generate_flamegraph(
                    self.mem_stacks, self.mem_svg,
                    f"内存分配火焰图 - {self.executable.name} ({self.sample_time}s)",
                    "memory"
                )

            # 5. 输出结果摘要
            self.print_summary()

            return True

        except KeyboardInterrupt:
            print("\n用户中断")
            return False
        except Exception as e:
            print(f"\n错误: {e}")
            import traceback
            traceback.print_exc()
            return False

    def print_summary(self):
        """输出分析结果摘要"""
        print("\n" + "="*60)
        print("性能分析完成!")
        print("="*60)
        print(f"输出目录: {self.output_dir}")
        print()

        if self.cpu_svg.exists():
            print(f"✓ CPU火焰图: file://{self.cpu_svg.resolve()}")
        else:
            print(f"✗ CPU火焰图: 生成失败")

        if self.enable_memory:
            if self.mem_svg.exists():
                print(f"✓ 内存火焰图: file://{self.mem_svg.resolve()}")
            else:
                print(f"✗ 内存火焰图: 生成失败")

        print("\n原始数据文件:")
        for file in self.output_dir.iterdir():
            if file.is_file():
                size = file.stat().st_size
                print(f"  {file.name} ({size:,} 字节)")

        print("\n提示:")
        print("  1. 在浏览器中打开SVG文件查看火焰图")
        print("  2. 点击火焰图中的任何部分可以放大")
        print("  3. 使用Ctrl+F在火焰图中搜索函数名")
        print("="*60)

def main():
    parser = argparse.ArgumentParser(
        description='通用火焰图性能分析工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 基本用法 - 分析30秒
  python3 flamegraph_profiler.py --executable ./myapp

  # 指定采样时间和输出目录
  python3 flamegraph_profiler.py --executable ./myapp --time 60 --output ./profiles

  # 仅CPU分析
  python3 flamegraph_profiler.py --executable ./myapp --no-memory

  # 设置CPU采样频率
  python3 flamegraph_profiler.py --executable ./myapp --freq 199
        """
    )

    parser.add_argument('--executable', '-e', required=True,
                       help='要分析的可执行文件路径')
    parser.add_argument('--time', '-t', type=int, default=DEFAULT_SAMPLE_TIME,
                       help=f'采样时间(秒)，默认: {DEFAULT_SAMPLE_TIME}')
    parser.add_argument('--freq', '-f', type=int, default=DEFAULT_CPU_FREQ,
                       help=f'CPU采样频率(Hz)，默认: {DEFAULT_CPU_FREQ}')
    parser.add_argument('--output', '-o',
                       help='输出目录，默认: ./flamegraph_YYYYMMDD_HHMMSS')
    parser.add_argument('--no-memory', action='store_true',
                       help='禁用内存分析')
    parser.add_argument('--flamegraph-dir',
                       help=f'FlameGraph目录路径，默认: {FLAMEGRAPH_DIR} 或环境变量FLAMEGRAPH_DIR')

    args = parser.parse_args()

    # 设置FlameGraph目录
    flamegraph_dir = args.flamegraph_dir or FLAMEGRAPH_DIR
    if flamegraph_dir:
        os.environ['FLAMEGRAPH_DIR'] = flamegraph_dir

    try:
        profiler = FlamegraphProfiler(
            executable=args.executable,
            output_dir=args.output,
            sample_time=args.time,
            cpu_freq=args.freq,
            enable_memory=not args.no_memory
        )

        success = profiler.run()
        sys.exit(0 if success else 1)

    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()