#!/usr/bin/env python3
"""
通用火焰图性能分析工具
支持通过配置文件管理多个项目

用法：
    python3 generic_profiler.py [选项]

示例：
    # 使用默认配置文件分析所有项目
    python3 generic_profiler.py

    # 分析特定项目
    python3 generic_profiler.py --project liii

    # 使用自定义配置文件
    python3 generic_profiler.py --config my_projects.yaml

    # 覆盖采样时间
    python3 generic_profiler.py --time 60

    # 仅构建不分析
    python3 generic_profiler.py --build-only
"""

import os
import sys
import time
import subprocess
import argparse
import shutil
import yaml
import signal
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any

# 默认配置文件路径
DEFAULT_CONFIG = Path(__file__).parent / 'projects.yaml'

class ProjectConfig:
    """项目配置类"""
    def __init__(self, name: str, config: Dict[str, Any]):
        self.name = name
        self.path = Path(config.get('path', '')).expanduser().resolve()
        self.output_dir = Path(config.get('output_dir', '')).expanduser().resolve()
        self.build_cmds = config.get('build_cmds', [])
        self.executable = config.get('executable', '')
        self.target = config.get('target', '')
        self.args = config.get('args', [])
        self.env = config.get('env', {})
        self.startup_delay = config.get('startup_delay', 3)

        # 确保输出目录存在
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def validate(self):
        """验证配置"""
        errors = []

        if not self.path.exists():
            errors.append(f"项目路径不存在: {self.path}")

        if not self.executable:
            errors.append("未指定可执行文件名称")

        return errors

class GlobalConfig:
    """全局配置类"""
    def __init__(self, config: Dict[str, Any]):
        self.default_sample_time = config.get('default_sample_time', 30)
        self.default_cpu_freq = config.get('default_cpu_freq', 99)
        self.enable_memory = config.get('enable_memory', True)
        self.flamegraph_dir = Path(config.get('flamegraph_dir', '/Users/yuki/git/FlameGraph')).expanduser().resolve()
        self.skip_build = config.get('skip_build', False)
        self.build_timeout = config.get('build_timeout', 300)
        self.profiling_timeout = config.get('profiling_timeout', 600)

    def validate(self):
        """验证配置"""
        errors = []

        if not self.flamegraph_dir.exists():
            errors.append(f"FlameGraph目录不存在: {self.flamegraph_dir}")

        return errors

class GenericProfiler:
    """通用性能分析器"""

    def __init__(self, project_config: ProjectConfig, global_config: GlobalConfig,
                 sample_time: Optional[int] = None, cpu_freq: Optional[int] = None,
                 enable_memory: Optional[bool] = None, skip_build: Optional[bool] = None):

        self.project = project_config
        self.global_config = global_config

        # 使用参数值或全局默认值
        self.sample_time = sample_time or global_config.default_sample_time
        self.cpu_freq = cpu_freq or global_config.default_cpu_freq
        self.enable_memory = enable_memory if enable_memory is not None else global_config.enable_memory
        self.skip_build = skip_build if skip_build is not None else global_config.skip_build

        # 设置日志文件
        self.log_file = self.project.output_dir / 'profiling.log'
        self.build_log = self.project.output_dir / 'build.log'

        # 进程引用
        self.target_process = None
        self.dtrace_processes = []

        # 文件路径
        self.cpu_stacks = self.project.output_dir / 'cpu.stacks'
        self.cpu_folded = self.project.output_dir / 'cpu.folded'
        self.cpu_svg = self.project.output_dir / 'cpu.svg'

        self.mem_stacks = self.project.output_dir / 'memory.stacks'
        self.mem_folded = self.project.output_dir / 'memory.folded'
        self.mem_svg = self.project.output_dir / 'memory.svg'

        # 验证FlameGraph工具
        self.flamegraph_dir = global_config.flamegraph_dir
        self._check_flamegraph_tools()

        print(f"\n{'='*60}")
        print(f"项目: {self.project.name}")
        print(f"路径: {self.project.path}")
        print(f"输出目录: {self.project.output_dir}")
        print(f"采样时间: {self.sample_time}秒")
        print(f"CPU频率: {self.cpu_freq} Hz")
        print(f"内存分析: {'启用' if self.enable_memory else '禁用'}")
        print(f"跳过构建: {self.skip_build}")
        print(f"{'='*60}")

    def _check_flamegraph_tools(self):
        """检查FlameGraph工具"""
        required_scripts = ['stackcollapse.pl', 'flamegraph.pl']
        for script in required_scripts:
            script_path = self.flamegraph_dir / script
            if not script_path.exists():
                raise FileNotFoundError(f"FlameGraph脚本不存在: {script_path}")

    def log(self, message: str, level: str = 'INFO'):
        """记录日志"""
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        log_msg = f"[{timestamp}] [{level}] {message}"
        print(log_msg)
        with open(self.log_file, 'a') as f:
            f.write(log_msg + '\n')

    def run_command(self, cmd: str, description: str = None,
                   cwd: Optional[Path] = None, check: bool = True,
                   timeout: Optional[int] = None) -> subprocess.CompletedProcess:
        """运行命令并记录输出"""
        if description:
            self.log(f"开始: {description}")

        if cwd is None:
            cwd = self.project.path

        self.log(f"执行命令: {cmd}")
        self.log(f"工作目录: {cwd}")

        try:
            # 设置环境变量
            env = os.environ.copy()
            env.update(self.project.env)

            result = subprocess.run(
                cmd,
                shell=True,
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout or self.global_config.build_timeout,
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

    def find_executable(self) -> Path:
        """查找可执行文件"""
        # 如果指定的是绝对路径或相对路径，直接使用
        exe_candidate = Path(self.project.executable)
        if exe_candidate.is_absolute():
            if exe_candidate.exists() and os.access(exe_candidate, os.X_OK):
                self.log(f"找到可执行文件: {exe_candidate}")
                return exe_candidate
        else:
            # 尝试在项目目录中查找
            exe_in_project = self.project.path / exe_candidate
            if exe_in_project.exists() and os.access(exe_in_project, os.X_OK):
                self.log(f"找到可执行文件: {exe_in_project}")
                return exe_in_project

            # 尝试在构建目录中查找
            build_dirs = [
                self.project.path / 'build' / 'macosx' / 'arm64' / 'release',
                self.project.path / 'build' / 'macosx' / 'x86_64' / 'release',
                self.project.path / 'build' / 'macosx' / 'arm64' / 'debug',
                self.project.path / 'build' / 'macosx' / 'x86_64' / 'debug',
                self.project.path / 'build',
                self.project.path / 'bin',
            ]

            for build_dir in build_dirs:
                if build_dir.exists():
                    exe_path = build_dir / exe_candidate
                    if exe_path.exists():
                        if exe_path.is_dir() and exe_path.suffix == '.app':
                            # macOS应用程序包
                            macos_dir = exe_path / 'Contents' / 'MacOS'
                            if macos_dir.exists():
                                for file in macos_dir.iterdir():
                                    if file.is_file() and os.access(file, os.X_OK):
                                        self.log(f"找到可执行文件: {file}")
                                        return file
                        elif os.access(exe_path, os.X_OK):
                            self.log(f"找到可执行文件: {exe_path}")
                            return exe_path

            # 尝试通配符查找
            for build_dir in build_dirs:
                if build_dir.exists():
                    for file in build_dir.rglob(f"*{exe_candidate}*"):
                        if file.is_file() and os.access(file, os.X_OK):
                            self.log(f"找到可执行文件: {file}")
                            return file

        raise FileNotFoundError(
            f"找不到可执行文件: {self.project.executable}\n"
            f"请确保项目已构建，或在配置中指定正确的可执行文件路径。"
        )

    def build_project(self):
        """构建项目"""
        if self.skip_build:
            self.log("跳过构建")
            return

        self.log(f"开始构建项目: {self.project.name}")

        # 执行构建命令
        for i, cmd in enumerate(self.project.build_cmds):
            self.run_command(
                cmd,
                description=f"构建步骤 {i+1}/{len(self.project.build_cmds)}",
                timeout=self.global_config.build_timeout
            )

        self.log(f"项目构建完成: {self.project.name}")

    def run_dtrace_analysis(self, pid: int, script: str, output_file: Path, description: str):
        """运行dtrace分析脚本"""
        self.log(f"启动{description} (PID: {pid})")

        with open(output_file, 'w') as f:
            process = subprocess.Popen(
                ['sudo', 'dtrace', '-x', 'ustackframes=100', '-n', script],
                stdout=f,
                stderr=subprocess.PIPE,
                text=True
            )
            self.dtrace_processes.append(process)

        # 等待dtrace进程完成
        try:
            process.wait(timeout=self.sample_time + 10)
            self.log(f"{description}完成")
        except subprocess.TimeoutExpired:
            self.log(f"{description}超时", level='WARNING')
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()

    def run_cpu_analysis(self, pid: int):
        """运行CPU分析"""
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
        self.run_dtrace_analysis(pid, script, self.cpu_stacks, "CPU分析")

    def run_memory_analysis(self, pid: int):
        """运行内存分析"""
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
    exit(0);
}}
"""
        self.run_dtrace_analysis(pid, script, self.mem_stacks, "内存分析")

    def generate_flamegraph(self, input_file: Path, output_svg: Path, title: str) -> bool:
        """生成火焰图"""
        if not input_file.exists() or input_file.stat().st_size == 0:
            self.log(f"输入文件为空: {input_file}", level='WARNING')
            return False

        try:
            # 折叠堆栈
            collapse_script = self.flamegraph_dir / 'stackcollapse.pl'
            folded_file = input_file.with_suffix('.folded')

            self.log(f"折叠堆栈数据: {input_file}")
            with open(folded_file, 'w') as outfile:
                subprocess.run(
                    [str(collapse_script), str(input_file)],
                    stdout=outfile,
                    stderr=subprocess.PIPE,
                    check=True
                )

            # 生成SVG火焰图
            flamegraph_script = self.flamegraph_dir / 'flamegraph.pl'

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

    def run_target_with_profiling(self, executable: Path):
        """运行目标程序并进行性能分析"""
        self.log(f"启动目标程序: {executable}")

        # 准备命令行参数
        cmd = [str(executable)] + self.project.args

        # 启动目标程序
        self.target_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid,
            env={**os.environ, **self.project.env}
        )

        # 等待程序启动
        self.log(f"等待程序启动 ({self.project.startup_delay}秒)...")
        time.sleep(self.project.startup_delay)

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
                cpu_thread = threading.Thread(target=self.run_cpu_analysis, args=(pid,))
                mem_thread = threading.Thread(target=self.run_memory_analysis, args=(pid,))

                cpu_thread.start()
                mem_thread.start()

                cpu_thread.join()
                mem_thread.join()
            else:
                # 仅CPU分析
                self.run_cpu_analysis(pid)

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
                    try:
                        proc.kill()
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

    def run(self) -> bool:
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
                    f"CPU火焰图 - {self.project.name} ({self.sample_time}s)"
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
                    f"内存分配火焰图 - {self.project.name} ({self.sample_time}s)"
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
        self.log(f"项目: {self.project.name}")
        self.log(f"输出目录: {self.project.output_dir}")

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
        for file in self.project.output_dir.iterdir():
            if file.is_file():
                size = file.stat().st_size
                self.log(f"  {file.name} ({size:,} 字节)")

        self.log("="*60)

def load_config(config_file: Path) -> tuple[Dict[str, ProjectConfig], GlobalConfig]:
    """加载配置文件"""
    if not config_file.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_file}")

    with open(config_file, 'r') as f:
        config_data = yaml.safe_load(f)

    if not config_data:
        raise ValueError("配置文件为空或格式错误")

    # 加载全局配置
    global_data = config_data.get('global', {})
    global_config = GlobalConfig(global_data)

    # 加载项目配置
    projects_data = config_data.get('projects', {})
    projects = {}

    for name, project_data in projects_data.items():
        projects[name] = ProjectConfig(name, project_data)

    return projects, global_config

def main():
    parser = argparse.ArgumentParser(
        description='通用火焰图性能分析工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 使用默认配置文件分析所有项目
  python3 generic_profiler.py

  # 分析特定项目
  python3 generic_profiler.py --project liii

  # 使用自定义配置文件
  python3 generic_profiler.py --config my_projects.yaml

  # 覆盖采样时间
  python3 generic_profiler.py --time 60

  # 仅构建不分析
  python3 generic_profiler.py --build-only
        """
    )

    parser.add_argument('--config', '-c', type=Path, default=DEFAULT_CONFIG,
                       help=f'配置文件路径，默认: {DEFAULT_CONFIG}')
    parser.add_argument('--project', '-p', action='append',
                       help='要分析的项目名称（可多次指定），默认: 所有项目')
    parser.add_argument('--time', '-t', type=int,
                       help='采样时间(秒)，覆盖配置文件中的默认值')
    parser.add_argument('--freq', '-f', type=int,
                       help='CPU采样频率(Hz)，覆盖配置文件中的默认值')
    parser.add_argument('--no-memory', action='store_true',
                       help='禁用内存分析，覆盖配置文件中的设置')
    parser.add_argument('--no-build', action='store_true',
                       help='跳过构建步骤，覆盖配置文件中的设置')
    parser.add_argument('--build-only', action='store_true',
                       help='仅构建，不进行性能分析')
    parser.add_argument('--flamegraph-dir', type=Path,
                       help='FlameGraph目录路径，覆盖配置文件中的设置')

    args = parser.parse_args()

    try:
        # 加载配置
        projects, global_config = load_config(args.config)

        # 覆盖全局配置
        if args.flamegraph_dir:
            global_config.flamegraph_dir = args.flamegraph_dir.expanduser().resolve()

        # 验证全局配置
        errors = global_config.validate()
        if errors:
            for error in errors:
                print(f"配置错误: {error}")
            sys.exit(1)

        # 确定要分析的项目
        if args.project:
            projects_to_analyze = []
            for project_name in args.project:
                if project_name not in projects:
                    print(f"错误: 项目 '{project_name}' 不在配置文件中")
                    sys.exit(1)
                projects_to_analyze.append(project_name)
        else:
            projects_to_analyze = list(projects.keys())

        if not projects_to_analyze:
            print("错误: 没有要分析的项目")
            sys.exit(1)

        # 验证项目配置
        for project_name in projects_to_analyze:
            project_config = projects[project_name]
            errors = project_config.validate()
            if errors:
                for error in errors:
                    print(f"项目 '{project_name}' 配置错误: {error}")
                sys.exit(1)

        # 分析每个项目
        results = {}

        for project_name in projects_to_analyze:
            project_config = projects[project_name]

            profiler = GenericProfiler(
                project_config=project_config,
                global_config=global_config,
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

    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()