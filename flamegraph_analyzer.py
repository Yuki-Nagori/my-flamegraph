#!/usr/bin/env python3
"""
火焰图数据分析器
"""

import sys
import argparse
from collections import defaultdict
from typing import Dict, List, Tuple, Set, Optional
import time
import os


class FlameGraphAnalyzer:
    """火焰图数据分析器"""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.inclusive_time = defaultdict(int)  # 函数自包含时间
        self.exclusive_time = defaultdict(int)  # 函数独占时间
        self.call_relations = defaultdict(set)  # 调用关系
        self.leaf_counts = defaultdict(int)     # 叶子节点计数
        self.func_counts = defaultdict(int)     # 函数出现次数
        self.total_samples = 0
        self.parsed_lines = 0
        self.line_count = 0

        # 内存分配相关
        self.malloc_counts = defaultdict(int)   # 内存分配次数
        self.free_counts = defaultdict(int)     # 内存释放次数
        self.alloc_size = defaultdict(int)      # 分配总大小（如果数据中包含）

        # 类别分析
        self.categories = {
            'MoganSTEM': 'MoganSTEM',
            'Qt': 'Qt',
            'AppKit': 'AppKit',
            'CoreFoundation': 'CoreFoundation',
            'libsystem_malloc': 'libsystem_malloc',
            'libsystem_kernel': 'libsystem_kernel',
            'QuartzCore': 'QuartzCore',
            'Foundation': 'Foundation',
            'HIToolbox': 'HIToolbox',
            'CoreText': 'CoreText',
            'iiiSTEM': 'iiiSTEM',
            'libqcocoa': 'libqcocoa.dylib',
            'libqsvgicon': 'libqsvgicon.dylib',
            'libxpc': 'libxpc.dylib',
            'libdispatch': 'libdispatch.dylib',
            'libobjc': 'libobjc.A.dylib',
            'libswiftCore': 'libswiftCore.dylib'
        }
        self.category_counts = defaultdict(int)

    def parse_file(self):
        """解析folded格式文件"""
        print(f"正在解析文件: {self.file_path}")
        start_time = time.time()

        with open(self.file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line_num, line in enumerate(f, 1):
                self.line_count += 1
                line = line.strip()
                if not line:
                    continue

                # 尝试解析 folded 格式：函数栈;计数
                parts = line.rsplit(';', 1)
                if len(parts) != 2:
                    # 尝试其他分隔符（兼容simple_analyze.py）
                    if ' ' in line:
                        parts = line.rsplit(' ', 1)

                if len(parts) == 2:
                    stack_str, count_str = parts
                    try:
                        count = int(count_str)
                    except ValueError:
                        # 如果不是数字，假设计数为1
                        count = 1
                        stack_str = line
                else:
                    # 无法解析，假设整行都是调用栈，计数为1
                    stack_str = line
                    count = 1

                self.total_samples += count
                self.parsed_lines += 1

                # 分割调用栈
                stack = stack_str.split(';')
                if not stack:
                    continue

                # 1. 记录函数出现次数（simple_analyze.py功能）
                for func in stack:
                    if func:
                        self.func_counts[func] += count

                # 2. 记录调用关系（analyze.py功能）
                for i in range(len(stack) - 1):
                    caller = stack[i]
                    callee = stack[i + 1]
                    self.call_relations[caller].add(callee)

                # 3. 计算自包含时间（analyze.py功能）
                for func in stack:
                    self.inclusive_time[func] += count

                # 4. 计算独占时间（叶子节点）
                if stack:
                    leaf_func = stack[-1]
                    self.exclusive_time[leaf_func] += count
                    self.leaf_counts[leaf_func] += count

                # 5. 分析内存分配函数（leaf_analysis.py功能扩展）
                if stack:
                    leaf_func = stack[-1]
                    if 'malloc' in leaf_func or 'calloc' in leaf_func or 'realloc' in leaf_func:
                        self.malloc_counts[leaf_func] += count
                    elif 'free' in leaf_func:
                        self.free_counts[leaf_func] += count

        # 6. 计算类别分布
        for func, count in self.func_counts.items():
            categorized = False
            for cat_name, cat_prefix in self.categories.items():
                if cat_prefix in func:
                    self.category_counts[cat_name] += count
                    categorized = True
                    break
            if not categorized:
                self.category_counts['其他'] += count

        elapsed = time.time() - start_time
        print(f"解析完成，耗时: {elapsed:.2f}秒")
        print(f"总行数: {self.line_count}")
        print(f"解析行数: {self.parsed_lines}")
        print(f"总采样数: {self.total_samples}")
        print(f"唯一函数数: {len(self.func_counts)}")
        print(f"唯一叶子函数数: {len(self.leaf_counts)}")
        print()

    def print_basic_stats(self):
        """输出基本统计信息"""
        print("=" * 80)
        print("火焰图分析报告")
        print("=" * 80)
        print(f"文件: {self.file_path}")
        print(f"采样总数: {self.total_samples}")
        print(f"唯一函数: {len(self.func_counts)}")
        print(f"调用关系: {sum(len(v) for v in self.call_relations.values())} 条")
        print()

    def print_inclusive_time_top(self, top_n: int = 20):
        """输出自包含时间排行榜"""
        print("=" * 80)
        print("自包含时间排行榜（包含子函数）")
        print("=" * 80)
        sorted_inclusive = sorted(self.inclusive_time.items(), key=lambda x: x[1], reverse=True)
        for i, (func, time_val) in enumerate(sorted_inclusive[:top_n], 1):
            percentage = (time_val / self.total_samples) * 100
            print(f"{i:3d}. {func[:100]:100s} {time_val:8d} ({percentage:6.2f}%)")
        print()

    def print_exclusive_time_top(self, top_n: int = 20):
        """输出独占时间排行榜"""
        print("=" * 80)
        print("独占时间排行榜（叶子节点，不包含子函数）")
        print("=" * 80)
        sorted_exclusive = sorted(self.exclusive_time.items(), key=lambda x: x[1], reverse=True)
        for i, (func, time_val) in enumerate(sorted_exclusive[:top_n], 1):
            percentage = (time_val / self.total_samples) * 100
            print(f"{i:3d}. {func[:100]:100s} {time_val:8d} ({percentage:6.2f}%)")
        print()

    def print_leaf_functions_top(self, top_n: int = 30):
        """输出叶子节点函数排行榜"""
        print("=" * 80)
        print("叶子节点函数排行榜（独占时间）")
        print("=" * 80)
        sorted_leaves = sorted(self.leaf_counts.items(), key=lambda x: x[1], reverse=True)
        for i, (func, count) in enumerate(sorted_leaves[:top_n], 1):
            percentage = (count / self.total_samples) * 100
            print(f"{i:3d}. {func[:120]:120s} {count:6d} ({percentage:6.2f}%)")
        print()

    def print_category_analysis(self):
        """输出类别分析"""
        print("=" * 80)
        print("按类别分析")
        print("=" * 80)
        print("类别分布:")
        for cat, count in sorted(self.category_counts.items(), key=lambda x: x[1], reverse=True):
            percentage = (count / self.total_samples) * 100
            print(f"  {cat:20s} {count:8d} ({percentage:6.2f}%)")
        print()

    def print_memory_analysis(self):
        """输出内存分析"""
        print("=" * 80)
        print("内存分配相关函数分析")
        print("=" * 80)

        # 合并所有内存分配/释放函数
        all_memory_funcs = set(self.malloc_counts.keys()) | set(self.free_counts.keys())
        memory_stats = []

        for func in all_memory_funcs:
            malloc_count = self.malloc_counts.get(func, 0)
            free_count = self.free_counts.get(func, 0)
            total = malloc_count + free_count
            if total > 0:
                memory_stats.append((func, malloc_count, free_count, total))

        # 按总次数排序
        memory_stats.sort(key=lambda x: x[3], reverse=True)

        print(f"内存相关函数总数: {len(memory_stats)}")
        print()

        if memory_stats:
            print("内存函数统计 (分配次数 / 释放次数 / 总计):")
            for i, (func, malloc, free, total) in enumerate(memory_stats[:20], 1):
                malloc_pct = (malloc / self.total_samples) * 100 if self.total_samples > 0 else 0
                free_pct = (free / self.total_samples) * 100 if self.total_samples > 0 else 0
                total_pct = (total / self.total_samples) * 100 if self.total_samples > 0 else 0
                print(f"{i:3d}. {func[:100]:100s} 分配:{malloc:5d}({malloc_pct:5.2f}%) 释放:{free:5d}({free_pct:5.2f}%) 总计:{total:5d}({total_pct:5.2f}%)")

            # 计算分配/释放比例
            total_malloc = sum(self.malloc_counts.values())
            total_free = sum(self.free_counts.values())
            print()
            print(f"总分配次数: {total_malloc} ({(total_malloc/self.total_samples*100):.2f}%)")
            print(f"总释放次数: {total_free} ({(total_free/self.total_samples*100):.2f}%)")
            if total_malloc > 0:
                ratio = total_free / total_malloc
                print(f"释放/分配比例: {ratio:.3f}")
                if ratio < 0.8:
                    print("警告: 释放次数明显少于分配次数，可能存在内存泄漏风险")
                elif ratio > 1.2:
                    print("注意: 释放次数多于分配次数，可能是缓存释放或采样偏差")

            # 检测潜在内存泄漏点（分配次数远大于释放次数的函数）
            print()
            print("潜在内存泄漏风险点（分配次数 > 释放次数 * 2）:")
            leak_candidates = []
            for func, malloc, free, total in memory_stats:
                if malloc > 0 and free > 0:
                    if malloc > free * 2 and malloc - free > 10:  # 分配次数是释放次数的2倍以上，且差值大于10
                        leak_candidates.append((func, malloc, free, malloc - free))

            leak_candidates.sort(key=lambda x: x[3], reverse=True)  # 按差值排序
            if leak_candidates:
                for i, (func, malloc, free, diff) in enumerate(leak_candidates[:10], 1):
                    ratio = free / malloc if malloc > 0 else 0
                    print(f"{i:3d}. {func[:100]:100s} 分配:{malloc:5d} 释放:{free:5d} 差值:{diff:5d} 释放率:{ratio:.2f}")
            else:
                print("  (未发现明显的分配/释放不平衡函数)")

            # 分配热点分析（按分配次数排序）
            print()
            print("内存分配热点函数（按分配次数排序）:")
            malloc_hotspots = [(func, malloc) for func, malloc, free, total in memory_stats if malloc > 0]
            malloc_hotspots.sort(key=lambda x: x[1], reverse=True)
            for i, (func, malloc) in enumerate(malloc_hotspots[:10], 1):
                pct = (malloc / self.total_samples) * 100 if self.total_samples > 0 else 0
                print(f"{i:3d}. {func[:100]:100s} 分配次数:{malloc:5d} ({pct:5.2f}%)")

            # 释放热点分析
            print()
            print("内存释放热点函数（按释放次数排序）:")
            free_hotspots = [(func, free) for func, malloc, free, total in memory_stats if free > 0]
            free_hotspots.sort(key=lambda x: x[1], reverse=True)
            for i, (func, free) in enumerate(free_hotspots[:10], 1):
                pct = (free / self.total_samples) * 100 if self.total_samples > 0 else 0
                print(f"{i:3d}. {func[:100]:100s} 释放次数:{free:5d} ({pct:5.2f}%)")

        print()

    def print_moganstem_analysis(self):
        """输出MoganSTEM相关函数分析"""
        print("=" * 80)
        print("MoganSTEM相关函数分析")
        print("=" * 80)

        # 自包含时间中的MoganSTEM函数
        mogan_inclusive = [(f, t) for f, t in self.inclusive_time.items() if 'MoganSTEM' in f]
        mogan_inclusive.sort(key=lambda x: x[1], reverse=True)

        if mogan_inclusive:
            print(f"MoganSTEM函数数量 (自包含): {len(mogan_inclusive)}")
            print("Top MoganSTEM函数（自包含时间）:")
            for i, (func, time_val) in enumerate(mogan_inclusive[:15], 1):
                percentage = (time_val / self.total_samples) * 100
                print(f"{i:3d}. {func[:100]:100s} {time_val:8d} ({percentage:6.2f}%)")
        else:
            # 尝试iiiSTEM
            iii_inclusive = [(f, t) for f, t in self.inclusive_time.items() if 'iiiSTEM' in f]
            iii_inclusive.sort(key=lambda x: x[1], reverse=True)
            if iii_inclusive:
                print(f"iiiSTEM函数数量 (自包含): {len(iii_inclusive)}")
                print("Top iiiSTEM函数（自包含时间）:")
                for i, (func, time_val) in enumerate(iii_inclusive[:15], 1):
                    percentage = (time_val / self.total_samples) * 100
                    print(f"{i:3d}. {func[:100]:100s} {time_val:8d} ({percentage:6.2f}%)")
            else:
                print("未找到MoganSTEM或iiiSTEM相关函数")
        print()

    def print_performance_issues(self):
        """输出潜在性能问题分析"""
        print("=" * 80)
        print("潜在性能问题分析")
        print("=" * 80)

        # 高自包含时间的函数
        sorted_inclusive = sorted(self.inclusive_time.items(), key=lambda x: x[1], reverse=True)
        print("高自包含时间的函数（可能包含昂贵的子调用）:")
        high_inclusive = []
        for func, time_val in sorted_inclusive[:20]:
            percentage = (time_val / self.total_samples) * 100
            if percentage > 2.0:
                high_inclusive.append((func, percentage))
                print(f"  {func[:100]:100s} {percentage:6.2f}%")

        if not high_inclusive:
            print("  (无显著高自包含时间函数)")
        print()

        # 高独占时间的函数
        sorted_exclusive = sorted(self.exclusive_time.items(), key=lambda x: x[1], reverse=True)
        print("高独占时间的函数（函数自身代码耗时）:")
        high_exclusive = []
        for func, time_val in sorted_exclusive[:20]:
            percentage = (time_val / self.total_samples) * 100
            if percentage > 1.0:
                high_exclusive.append((func, percentage))
                print(f"  {func[:100]:100s} {percentage:6.2f}%")

        if not high_exclusive:
            print("  (无显著高独占时间函数)")
        print()

    def print_call_relations(self, top_n: int = 10):
        """输出调用关系分析"""
        print("=" * 80)
        print("调用关系分析（调用者最多的函数）")
        print("=" * 80)

        # 找出被调用最多的函数（被调用关系）
        callee_counts = defaultdict(int)
        for caller, callees in self.call_relations.items():
            for callee in callees:
                callee_counts[callee] += 1

        sorted_callees = sorted(callee_counts.items(), key=lambda x: x[1], reverse=True)
        print("被调用最多的函数:")
        for i, (func, count) in enumerate(sorted_callees[:top_n], 1):
            print(f"{i:3d}. {func[:100]:100s} 被 {count:3d} 个不同函数调用")
        print()

        # 找出调用其他函数最多的函数
        sorted_callers = sorted(self.call_relations.items(), key=lambda x: len(x[1]), reverse=True)
        print("调用其他函数最多的函数:")
        for i, (func, callees) in enumerate(sorted_callers[:top_n], 1):
            print(f"{i:3d}. {func[:100]:100s} 调用 {len(callees):3d} 个不同函数")
        print()

    def generate_report(self, output_file: str = None):
        """生成完整分析报告"""
        import sys

        old_stdout = sys.stdout
        if output_file:
            sys.stdout = open(output_file, 'w', encoding='utf-8')

        try:
            self.print_basic_stats()
            self.print_inclusive_time_top()
            self.print_exclusive_time_top()
            self.print_leaf_functions_top()
            self.print_category_analysis()
            self.print_memory_analysis()
            self.print_moganstem_analysis()
            self.print_performance_issues()
            self.print_call_relations()
        finally:
            if output_file:
                sys.stdout.close()
                sys.stdout = old_stdout
                print(f"报告已保存到: {output_file}")

    def run_analysis(self, output_file: str = None, report: bool = True):
        """运行完整分析流程"""
        self.parse_file()

        if report:
            self.generate_report(output_file)
        else:
            # 只输出到控制台
            self.print_basic_stats()
            self.print_inclusive_time_top()
            self.print_exclusive_time_top()
            self.print_leaf_functions_top()
            self.print_category_analysis()
            self.print_memory_analysis()
            self.print_moganstem_analysis()
            self.print_performance_issues()
            self.print_call_relations()


def main():
    parser = argparse.ArgumentParser(
        description='火焰图数据分析器（整合版）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 基本分析，输出到控制台
  python3 flamegraph_analyzer.py cpu.folded

  # 生成完整报告文件
  python3 flamegraph_analyzer.py cpu.folded --output report.txt

  # 仅运行特定分析（逗号分隔）
  python3 flamegraph_analyzer.py cpu.folded --analysis inclusive,exclusive,memory

  # 分析内存火焰图文件
  python3 flamegraph_analyzer.py memory.folded --analysis memory,category
        """
    )

    parser.add_argument('file', help='folded格式火焰图文件路径')
    parser.add_argument('--output', '-o', help='输出报告文件路径')
    parser.add_argument('--analysis', '-a',
                       help='指定分析类型（逗号分隔: inclusive,exclusive,leaf,category,memory,mogan,performance,call）',
                       default='all')
    parser.add_argument('--top', '-t', type=int, default=20,
                       help='排行榜显示数量（默认20）')
    parser.add_argument('--no-report', action='store_true',
                       help='不生成完整报告，只输出到控制台')

    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"错误: 文件不存在: {args.file}")
        sys.exit(1)

    analyzer = FlameGraphAnalyzer(args.file)
    analyzer.parse_file()

    if args.analysis == 'all' or args.no_report:
        # 运行完整分析
        analyzer.run_analysis(output_file=args.output, report=not args.no_report)
    else:
        # 运行指定分析
        analysis_types = [a.strip() for a in args.analysis.split(',')]

        # 输出基本统计
        analyzer.print_basic_stats()

        if 'inclusive' in analysis_types:
            analyzer.print_inclusive_time_top(args.top)
        if 'exclusive' in analysis_types:
            analyzer.print_exclusive_time_top(args.top)
        if 'leaf' in analysis_types:
            analyzer.print_leaf_functions_top(args.top)
        if 'category' in analysis_types:
            analyzer.print_category_analysis()
        if 'memory' in analysis_types:
            analyzer.print_memory_analysis()
        if 'mogan' in analysis_types:
            analyzer.print_moganstem_analysis()
        if 'performance' in analysis_types:
            analyzer.print_performance_issues()
        if 'call' in analysis_types:
            analyzer.print_call_relations(args.top)


if __name__ == '__main__':
    main()