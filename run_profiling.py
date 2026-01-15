#!/usr/bin/env python3
"""
自动化火焰图性能分析脚本
用于分析两个Mogan项目：liii/mogan 和 mogan

用法：
    python3 run_profiling.py [选项]

示例：
    # 默认分析两个项目，采样30秒
    python3 run_profiling.py

    # 仅分析一个项目
    python3 run_profiling.py --project liii
    python3 run_profiling.py --project mogan

    # 自定义采样时间
    python3 run_profiling.py --time 60

    # 不构建，仅分析
    python3 run_profiling.py --no-build

    # 仅构建，不分析
    python3 run_profiling.py --build-only
"""

import os
import sys
import time
import subprocess
import argparse
import shutil
from pathlib import Path
import signal

# 项目配置
PROJECTS = {
    'liii': {
        'path': Path('/Users/yuki/git/liii/mogan'),
        'output_dir': Path('/Users/yuki/git/fireimage/liii'),
        'build_cmd': 'xmake config -vD --yes -m --is_community=false',
        'binary_name': 'LiiiSTEM',  # 实际可执行文件名
        'target_name': 'stem',
    },
    'mogan': {
        'path': Path('/Users/yuki/git/mogan'),
        'output_dir': Path('/Users/yuki/git/fireimage/mogan'),
        'build_cmd': 'xmake config -vD --yes -m --is_community=false',
        'binary_name': 'stem',  # 需要确认实际名称
        'target_name': 'stem',
    }
}

# 默认配置
DEFAULT_SAMPLE_TIME = 30
DEFAULT_CPU_FREQ = 99
FLAMEGRAPH_DIR = Path('/Users/yuki/git/FlameGraph')

class ProjectProfiler:
    def __init__(self, project_name, config, sample_time=DEFAULT_SAMPLE_TIME,
                 cpu_freq=DEFAULT_CPU_FREQ, enable_memory=True, skip_build=False):
        self.project_name = project_name
        self.config = config
        self.sample_time = sample_time
        self.cpu_freq = cpu_freq
        self.enable_memory = enable_memory
        self.skip_build = skip_build

        # 路径
        self.project_path = config['path'].resolve()
        self.output_dir = config['output_dir'].resolve()
        self.binary_name = config['binary_name']
        self.target_name = config['target_name']

        # 确保输出目录存在
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 日志文件
        self.log_file = self.output_dir / 'profiling.log'
        self.build_log = self.output_dir / 'build.log'

        # 进程引用
        self.target_process = None
        self.dtrace_processes = []

        # 文件路径
        self.cpu_stacks = self.output_dir / 'cpu.stacks'
        self.cpu_folded = self.output_dir / 'cpu.folded'
        self.cpu_svg = self.output_dir / 'cpu.svg'

        self.mem_stacks = self.output_dir / 'memory.stacks'
        self.mem_folded = self.output_dir / 'memory.folded'
        self.mem_svg = self.output_dir / 'memory.svg'

        print(f"\n{'='*60}")
        print(f"项目: {project_name}")
        print(f"路径: {self.project_path}")
        print(f"输出目录: {self.output_dir}")
        print(f"采样时间: {sample_time}秒")
        print(f"CPU频率: {cpu_freq} Hz")
        print(f"内存分析: {'启用' if enable_memory else '禁用'}")
        print(f"跳过构建: {skip_build}")
        print(f"{'='*60}")

    def log(self, message, level='INFO'):
        """记录日志"""
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        log_msg = f"[{timestamp}] [{level}] {message}"
        print(log_msg)
        with open(self.log_file, 'a') as f:
            f.write(log_msg + '\n')

    def run_command(self, cmd, cwd=None, description=None, check=True, timeout=300):
        """运行命令并记录输出"""
        if description:
            self.log(f"开始: {description}")

        if cwd is None:
            cwd = self.project_path

        self.log(f"执行命令: {cmd}")
        self.log(f"工作目录: {cwd}")

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=check
            )

            if result.stdout:
                self.log(f"标准输出:\n{result.stdout[:1000]}...")
            if result.stderr:
                self.log(f"标准错误:\n{result.stderr[:1000]}...", level='WARNING')

            if description:
                self.log(f"完成: {description}")

            return result

        except subprocess.TimeoutExpired:
            self.log(f"超时: {description}", level='ERROR')
            raise
        except subprocess.CalledProcessError as e:
            self.log(f"命令失败: {description} (退出码: {e.returncode})", level='ERROR')
            if e.stderr:
                self.log(f"错误输出: {e.stderr[:1000]}", level='ERROR')
            raise

    def find_executable(self):
        """查找可执行文件"""
        # 尝试在构建目录中查找
        build_dirs = [
            self.project_path / 'build' / 'macosx' / 'arm64' / 'release',
            self.project_path / 'build' / 'macosx' / 'x86_64' / 'release',
            self.project_path / 'build' / 'macosx' / 'arm64' / 'debug',
            self.project_path / 'build' / 'macosx' / 'x86_64' / 'debug',
            self.project_path / 'build',
        ]

        for build_dir in build_dirs:
            if build_dir.exists():
                # 查找可执行文件
                for pattern in [self.binary_name, f'{self.binary_name}.app', 'stem', 'LiiiSTEM', 'MoganSTEM']:
                    exe_path = build_dir / pattern
                    if exe_path.exists():
                        if exe_path.is_dir() and exe_path.suffix == '.app':
                            # macOS应用程序包，查找内部的可执行文件
                            macos_dir = exe_path / 'Contents' / 'MacOS'
                            if macos_dir.exists():
                                for file in macos_dir.iterdir():
                                    if file.is_file() and os.access(file, os.X_OK):
                                        self.log(f"找到可执行文件: {file}")
                                        return file
                        elif os.access(exe_path, os.X_OK):
                            self.log(f"找到可执行文件: {exe_path}")
                            return exe_path

        # 如果没找到，尝试使用xmake show获取目标文件路径
        try:
            result = subprocess.run(
                ['xmake', 'show', '-l', 'targets'],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=30
            )

            # 查找目标文件
            target_file = self.project_path / 'build' / f'{self.target_name}'
            if target_file.exists() and os.access(target_file, os.X_OK):
                self.log(f"找到可执行文件: {target_file}")
                return target_file

        except Exception as e:
            self.log(f"使用xmake查找可执行文件失败: {e}", level='WARNING')

        raise FileNotFoundError(f"找不到可执行文件。请确保项目已构建。在以下目录中查找: {build_dirs}")

    def build_project(self):
        """构建项目"""
        if self.skip_build:
            self.log("跳过构建")
            return

        self.log(f"开始构建项目: {self.project_name}")

        # 清理构建目录（可选）
        # self.log("清理构建目录...")
        # try:
        #     shutil.rmtree(self.project_path / 'build', ignore_errors=True)
        # except Exception as e:
        #     self.log(f"清理失败: {e}", level='WARNING')

        # 运行配置命令
        config_cmd = self.config['build_cmd']
        self.run_command(config_cmd, description="配置项目")

        # 构建目标
        build_cmd = f"xmake b {self.target_name}"
        self.run_command(build_cmd, description=f"构建目标 {self.target_name}")

        self.log(f"项目构建完成: {self.project_name}")

    def run_dtrace_cpu(self, pid):
        """运行CPU分析的dtrace脚本"""
        script = f"""
#pragma D option quiet
#pragma D option stackframes=100
#pragma D option ustackframes=100
#pragma D option defaultargs

profile-{self.cpu_freq}
/pid == {pid}/
{{
    @[ustack()] = count();
}}

tick-{self.sample_time}s
{{
    exit(0);
}}
"""
        self.log(f"启动CPU分析 (PID: {pid})")
        with open(self.cpu_stacks, 'w') as f:
            process = subprocess.Popen(
                ['sudo', 'dtrace', '-x', 'ustackframes=100', '-n', script],
                stdout=f,
                stderr=subprocess.PIPE,
                text=True
            )
            self.dtrace_processes.append(process)

        # 等待dtrace进程完成
        try:
            process.wait(timeout=self.sample_time + 5)
            self.log(f"CPU分析完成")
        except subprocess.TimeoutExpired:
            self.log(f"CPU分析超时", level='WARNING')
            process.terminate()

    def run_dtrace_memory(self, pid):
        """运行内存分析的dtrace脚本"""
        script = f"""
#pragma D option quiet
#pragma D option stackframes=100
#pragma D option ustackframes=100
#pragma D option defaultargs

pid{pid}::malloc:entry
{{
    @alloc[ustack()] = sum(arg0);
    @count[ustack()] = count();
}}

pid{pid}::free:entry
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
        self.log(f"启动内存分析 (PID: {pid})")
        with open(self.mem_stacks, 'w') as f:
            process = subprocess.Popen(
                ['sudo', 'dtrace', '-x', 'ustackframes=100', '-n', script],
                stdout=f,
                stderr=subprocess.PIPE,
                text=True
            )
            self.dtrace_processes.append(process)

        # 等待dtrace进程完成
        try:
            process.wait(timeout=self.sample_time + 5)
            self.log(f"内存分析完成")
        except subprocess.TimeoutExpired:
            self.log(f"内存分析超时", level='WARNING')
            process.terminate()

    def generate_flamegraph(self, input_file, output_svg, title):
        """生成火焰图"""
        if not input_file.exists() or input_file.stat().st_size == 0:
            self.log(f"输入文件为空: {input_file}", level='WARNING')
            return False

        try:
            # 折叠堆栈
            collapse_script = FLAMEGRAPH_DIR / 'stackcollapse.pl'
            if not collapse_script.exists():
                raise FileNotFoundError(f"找不到折叠脚本: {collapse_script}")

            self.log(f"折叠堆栈数据: {input_file}")
            folded_file = input_file.with_suffix('.folded')
            with open(folded_file, 'w') as outfile:
                subprocess.run(
                    [str(collapse_script), str(input_file)],
                    stdout=outfile,
                    stderr=subprocess.PIPE,
                    check=True
                )

            # 生成SVG火焰图
            flamegraph_script = FLAMEGRAPH_DIR / 'flamegraph.pl'
            if not flamegraph_script.exists():
                raise FileNotFoundError(f"找不到火焰图脚本: {flamegraph_script}")

            self.log(f"生成火焰图: {output_svg}")
            with open(output_svg, 'w') as outfile:
                subprocess.run(
                    [str(flamegraph_script), f'--title={title}', str(folded_file)],
                    stdout=outfile,
                    stderr=subprocess.PIPE,
                    check=True
                )

            self.log(f"火焰图生成成功: {output_svg}")
            return True

        except subprocess.CalledProcessError as e:
            self.log(f"生成火焰图失败: {e}", level='ERROR')
            if e.stderr:
                self.log(f"错误输出: {e.stderr.decode('utf-8', errors='ignore')[:500]}", level='ERROR')
            return False
        except Exception as e:
            self.log(f"生成火焰图失败: {e}", level='ERROR')
            return False

    def run_target_with_profiling(self, executable):
        """运行目标程序并进行性能分析"""
        self.log(f"启动目标程序: {executable}")

        # 启动目标程序
        self.target_process = subprocess.Popen(
            [str(executable)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid
        )

        # 等待程序启动
        time.sleep(3)

        if self.target_process.poll() is not None:
            stderr = self.target_process.stderr.read().decode('utf-8', errors='ignore')
            self.log(f"目标程序过早退出: {stderr}", level='ERROR')
            raise RuntimeError("目标程序过早退出")

        pid = self.target_process.pid
        self.log(f"目标程序已启动 (PID: {pid})")

        try:
            # 启动dtrace分析
            if self.enable_memory:
                # 并行运行CPU和内存分析
                import threading

                def run_cpu():
                    self.run_dtrace_cpu(pid)

                def run_memory():
                    self.run_dtrace_memory(pid)

                cpu_thread = threading.Thread(target=run_cpu)
                mem_thread = threading.Thread(target=run_memory)

                cpu_thread.start()
                mem_thread.start()

                cpu_thread.join()
                mem_thread.join()
            else:
                # 仅CPU分析
                self.run_dtrace_cpu(pid)

            self.log("性能分析完成")

        finally:
            # 终止目标程序
            self.cleanup()

    def cleanup(self):
        """清理资源"""
        self.log("清理资源...")

        # 终止dtrace进程
        for proc in self.dtrace_processes:
            if proc and proc.poll() is None:
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

        self.log("清理完成")

    def run(self):
        """运行完整的分析流程"""
        try:
            # 1. 构建项目
            self.build_project()

            # 2. 查找可执行文件
            executable = self.find_executable()

            # 3. 运行程序并进行性能分析
            self.run_target_with_profiling(executable)

            # 4. 生成火焰图
            self.log("生成火焰图...")

            # CPU火焰图
            if self.cpu_stacks.exists() and self.cpu_stacks.stat().st_size > 0:
                success = self.generate_flamegraph(
                    self.cpu_stacks,
                    self.cpu_svg,
                    f"CPU火焰图 - {self.project_name} ({self.sample_time}s)"
                )
                if success:
                    self.log(f"CPU火焰图: {self.cpu_svg}")
                else:
                    self.log("CPU火焰图生成失败", level='WARNING')

            # 内存火焰图
            if self.enable_memory and self.mem_stacks.exists() and self.mem_stacks.stat().st_size > 0:
                success = self.generate_flamegraph(
                    self.mem_stacks,
                    self.mem_svg,
                    f"内存分配火焰图 - {self.project_name} ({self.sample_time}s)"
                )
                if success:
                    self.log(f"内存火焰图: {self.mem_svg}")
                else:
                    self.log("内存火焰图生成失败", level='WARNING')

            # 5. 输出摘要
            self.print_summary()

            return True

        except KeyboardInterrupt:
            self.log("用户中断", level='WARNING')
            self.cleanup()
            return False
        except Exception as e:
            self.log(f"分析失败: {e}", level='ERROR')
            import traceback
            self.log(traceback.format_exc(), level='ERROR')
            self.cleanup()
            return False

    def print_summary(self):
        """输出结果摘要"""
        self.log("\n" + "="*60)
        self.log("性能分析完成!")
        self.log("="*60)
        self.log(f"项目: {self.project_name}")
        self.log(f"输出目录: {self.output_dir}")

        if self.cpu_svg.exists():
            self.log(f"✓ CPU火焰图: {self.cpu_svg}")
        else:
            self.log("✗ CPU火焰图: 生成失败")

        if self.enable_memory:
            if self.mem_svg.exists():
                self.log(f"✓ 内存火焰图: {self.mem_svg}")
            else:
                self.log("✗ 内存火焰图: 生成失败")

        self.log("\n原始数据文件:")
        for file in self.output_dir.iterdir():
            if file.is_file():
                size = file.stat().st_size
                self.log(f"  {file.name} ({size:,} 字节)")

        self.log("="*60)

def main():
    parser = argparse.ArgumentParser(
        description='自动化火焰图性能分析工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 分析两个项目
  python3 run_profiling.py

  # 仅分析liii项目
  python3 run_profiling.py --project liii

  # 自定义采样时间
  python3 run_profiling.py --time 60

  # 不构建，仅分析
  python3 run_profiling.py --no-build

  # 仅构建，不分析
  python3 run_profiling.py --build-only
        """
    )

    parser.add_argument('--project', choices=['liii', 'mogan', 'all'],
                       default='all',
                       help='要分析的项目: liii, mogan, 或 all (默认)')
    parser.add_argument('--time', '-t', type=int, default=DEFAULT_SAMPLE_TIME,
                       help=f'采样时间(秒)，默认: {DEFAULT_SAMPLE_TIME}')
    parser.add_argument('--freq', '-f', type=int, default=DEFAULT_CPU_FREQ,
                       help=f'CPU采样频率(Hz)，默认: {DEFAULT_CPU_FREQ}')
    parser.add_argument('--no-memory', action='store_true',
                       help='禁用内存分析')
    parser.add_argument('--no-build', action='store_true',
                       help='跳过构建步骤')
    parser.add_argument('--build-only', action='store_true',
                       help='仅构建，不进行性能分析')
    parser.add_argument('--flamegraph-dir',
                       help=f'FlameGraph目录路径，默认: {FLAMEGRAPH_DIR}')

    args = parser.parse_args()

    # 设置FlameGraph目录
    global FLAMEGRAPH_DIR
    if args.flamegraph_dir:
        FLAMEGRAPH_DIR = Path(args.flamegraph_dir)

    if not FLAMEGRAPH_DIR.exists():
        print(f"错误: FlameGraph目录不存在: {FLAMEGRAPH_DIR}")
        sys.exit(1)

    # 确定要分析的项目
    if args.project == 'all':
        projects_to_analyze = ['liii', 'mogan']
    else:
        projects_to_analyze = [args.project]

    results = {}

    for project_name in projects_to_analyze:
        config = PROJECTS[project_name]

        profiler = ProjectProfiler(
            project_name=project_name,
            config=config,
            sample_time=args.time,
            cpu_freq=args.freq,
            enable_memory=not args.no_memory,
            skip_build=args.no_build
        )

        if args.build_only:
            try:
                profiler.build_project()
                results[project_name] = True
            except Exception as e:
                print(f"项目 {project_name} 构建失败: {e}")
                results[project_name] = False
        else:
            success = profiler.run()
            results[project_name] = success

    # 输出总体结果
    print("\n" + "="*60)
    print("分析完成摘要")
    print("="*60)
    for project_name, success in results.items():
        status = "✓ 成功" if success else "✗ 失败"
        print(f"{project_name}: {status}")
    print("="*60)

    # 如果有失败的项目，返回非零退出码
    if not all(results.values()):
        sys.exit(1)

if __name__ == '__main__':
    main()