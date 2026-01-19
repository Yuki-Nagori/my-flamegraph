#!/bin/bash
# 火焰图分析自动化脚本（交互式版本）
# 默认同时分析CPU和内存，可选择仅分析CPU

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 输出带颜色的消息
info() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 帮助信息
show_help() {
    cat << EOF
火焰图分析自动化脚本（交互式版本）

交互模式:
  运行脚本不带参数进入交互模式

命令行模式:
  $0 <目标> [选项]

目标:
  <项目名称>     - 配置在projects.yaml中的项目名称（如：liii, mogan）
  <文件路径>     - 已有的.folded文件路径（如：cpu.folded, memory.folded）

选项:
  -h, --help     显示此帮助信息
  -m, --memory   同时分析内存火焰图（默认）
  -c, --cpu-only 仅分析CPU火焰图
  -o, --output   指定输出目录（默认：analysis_results/）
  -r, --report-name 指定报告名称（不含扩展名，默认：analysis）
  -t, --time     采样时间（秒，默认：60）
  --no-profiling 不运行性能分析，仅分析已有文件

示例:
  # 交互模式
  $0

  # 命令行模式：分析liii项目
  $0 liii

  # 分析已有文件
  $0 liii/cpu.folded

  # 分析liii项目，仅分析CPU
  $0 liii --cpu-only

  # 指定输出目录
  $0 liii --output my_results/

  # 指定报告名称
  $0 liii --report-name myreport

  # 组合使用
  $0 liii --output my_results/ --report-name myreport --cpu-only
EOF
}

# 显示交互菜单
show_menu() {
    echo ""
    echo "========================================"
    echo "    火焰图分析工具 - 交互模式"
    echo "========================================"
    echo ""
}

# 获取用户输入
get_user_input() {
    local prompt="$1"
    local default="$2"
    local input

    if [[ -n "$default" ]]; then
        read -p "$prompt [$default]: " input
        input="${input:-$default}"
    else
        read -p "$prompt: " input
    fi

    echo "$input"
}

# 显示选择菜单
show_selection_menu() {
    local title="$1"
    shift
    local options=("$@")

    echo ""
    echo "$title"
    for i in "${!options[@]}"; do
        echo "  $((i+1)). ${options[$i]}"
    done
    echo ""
}

# 获取菜单选择
get_menu_selection() {
    local max="$1"
    local prompt="$2"
    local selection

    while true; do
        read -p "$prompt (1-$max): " selection
        if [[ "$selection" =~ ^[0-9]+$ ]] && ((selection >= 1 && selection <= max)); then
            break
        else
            echo "无效选择，请输入 1-$max 之间的数字"
        fi
    done

    echo "$selection"
}

# 解析命令行参数
parse_arguments() {
    # 初始化变量
    TARGET=""
    ANALYZE_MEMORY=true  # 默认同时分析内存
    OUTPUT_DIR="analysis_results"
    REPORT_NAME="analysis"  # 默认报告名称
    SAMPLE_TIME=60
    RUN_PROFILING=true
    INTERACTIVE=false

    # 如果没有参数，进入交互模式
    if [[ $# -eq 0 ]]; then
        INTERACTIVE=true
        return
    fi

    # 解析命令行参数
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_help
                exit 0
                ;;
            -m|--memory)
                ANALYZE_MEMORY=true
                shift
                ;;
            -c|--cpu-only)
                ANALYZE_MEMORY=false
                shift
                ;;
            -o|--output)
                OUTPUT_DIR="$2"
                shift 2
                ;;
            -t|--time)
                SAMPLE_TIME="$2"
                shift 2
                ;;
            -r|--report-name)
                REPORT_NAME="$2"
                shift 2
                ;;
            --no-profiling)
                RUN_PROFILING=false
                shift
                ;;
            -*)
                error "未知选项: $1"
                show_help
                exit 1
                ;;
            *)
                if [[ -z "$TARGET" ]]; then
                    TARGET="$1"
                else
                    error "多余参数: $1"
                    show_help
                    exit 1
                fi
                shift
                ;;
        esac
    done

    # 检查目标是否为空（在非交互模式下）
    if [[ "$INTERACTIVE" == false ]] && [[ -z "$TARGET" ]]; then
        error "请指定目标（项目名称或文件路径）"
        show_help
        exit 1
    fi
}

# 交互模式：获取用户输入
interactive_mode() {
    show_menu

    # 选择目标类型
    show_selection_menu "请选择分析目标类型:" \
        "分析项目（运行性能分析生成火焰图）" \
        "分析已有火焰图文件"

    TARGET_TYPE_SELECTION=$(get_menu_selection 2 "请选择")

    if [[ "$TARGET_TYPE_SELECTION" == "1" ]]; then
        # 分析项目
        echo ""
        echo "可用的项目（来自 projects.yaml）:"
        echo ""

        # 从projects.yaml提取项目列表
        if [[ -f "projects.yaml" ]]; then
            projects=$(grep "^  [a-zA-Z]" projects.yaml | cut -d: -f1 | sed 's/^  //')
            if [[ -n "$projects" ]]; then
                i=1
                for project in $projects; do
                    echo "  $i. $project"
                    PROJECT_LIST[$i]="$project"
                    ((i++))
                done
                echo ""

                PROJECT_COUNT=$((i-1))
                if (( PROJECT_COUNT > 0 )); then
                    PROJECT_SELECTION=$(get_menu_selection "$PROJECT_COUNT" "请选择项目")
                    TARGET="${PROJECT_LIST[$PROJECT_SELECTION]}"
                    TARGET_TYPE="project"
                else
                    error "projects.yaml中没有找到项目配置"
                    exit 1
                fi
            else
                error "无法从projects.yaml中提取项目列表"
                exit 1
            fi
        else
            error "未找到projects.yaml文件"
            exit 1
        fi
    else
        # 分析已有文件或目录
        echo ""
        TARGET=$(get_user_input "请输入.folded文件路径或包含火焰图文件的目录" "")
        if [[ ! -e "$TARGET" ]]; then
            error "文件或目录不存在: $TARGET"
            exit 1
        fi

        # 确定目标类型
        if [[ -f "$TARGET" ]]; then
            TARGET_TYPE="file"
        elif [[ -d "$TARGET" ]]; then
            TARGET_TYPE="folder"
        else
            error "目标既不是文件也不是目录: $TARGET"
            exit 1
        fi
    fi

    # 选择分析类型（所有目标类型）
    echo ""
    show_selection_menu "请选择分析类型:" \
        "CPU + 内存分析（默认）" \
        "仅CPU分析" \
        "仅内存分析"

    ANALYSIS_SELECTION=$(get_menu_selection 3 "请选择")
    case $ANALYSIS_SELECTION in
        1)
            ANALYSIS_TYPE="both"
            ANALYZE_MEMORY=true
            ;;
        2)
            ANALYSIS_TYPE="cpu"
            ANALYZE_MEMORY=false
            ;;
        3)
            ANALYSIS_TYPE="memory"
            ANALYZE_MEMORY=true
            ;;
    esac

    # 对于项目目标，选择是否运行性能分析
    if [[ "$TARGET_TYPE" == "project" ]]; then
        echo ""
        show_selection_menu "请选择操作:" \
            "运行性能分析生成火焰图（默认）" \
            "仅分析已有火焰图文件（不运行性能分析）"

        PROFILING_SELECTION=$(get_menu_selection 2 "请选择")
        if [[ "$PROFILING_SELECTION" == "2" ]]; then
            RUN_PROFILING=false
        else
            RUN_PROFILING=true
        fi

        # 设置采样时间（如果运行性能分析）
        if [[ "$RUN_PROFILING" == true ]]; then
            echo ""
            SAMPLE_TIME=$(get_user_input "请输入采样时间（秒）" "60")
        fi
    else
        # 对于文件和目录，不运行性能分析
        RUN_PROFILING=false
    fi

    # 设置输出目录
    echo ""
    OUTPUT_DIR=$(get_user_input "请输入输出目录" "analysis_results")

    # 设置报告名称
    REPORT_NAME=$(get_user_input "请输入报告名称（不含扩展名）" "analysis")
}

# 主分析函数
run_analysis() {
    # 创建输出目录
    mkdir -p "$OUTPUT_DIR"
    info "输出目录: $(realpath "$OUTPUT_DIR")"

    # 检查目标是文件还是项目名称
    if [[ -f "$TARGET" ]]; then
        # 目标是文件
        FOLDED_FILE="$TARGET"
        FILENAME=$(basename "$FOLDED_FILE")
        PROJECT_NAME="${FILENAME%.*}"

        info "分析文件: $FOLDED_FILE"

        # 检查文件类型与用户选择是否匹配
        if [[ "$ANALYSIS_TYPE" == "cpu" ]] && [[ ! "$FILENAME" =~ cpu && ! "$FILENAME" =~ CPU ]]; then
            warning "您选择了'仅CPU分析'，但文件名 '$FILENAME' 不包含'cpu'字样"
            warning "将继续分析文件，但请注意这可能不是CPU火焰图数据"
        fi

        if [[ "$ANALYSIS_TYPE" == "memory" ]] && [[ ! "$FILENAME" =~ memory && ! "$FILENAME" =~ Memory && ! "$FILENAME" =~ mem && ! "$FILENAME" =~ MEM ]]; then
            warning "您选择了'仅内存分析'，但文件名 '$FILENAME' 不包含'memory'或'mem'字样"
            warning "将继续分析文件，但请注意这可能不是内存火焰图数据"
        fi

        # 创建项目输出子目录
        PROJECT_OUTPUT_DIR="$OUTPUT_DIR/$PROJECT_NAME"
        mkdir -p "$PROJECT_OUTPUT_DIR"

        # 生成报告文件名
        TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
        REPORT_FILE="$PROJECT_OUTPUT_DIR/${REPORT_NAME}_${PROJECT_NAME}_${TIMESTAMP}.txt"

        # 运行分析
        info "运行火焰图分析..."
        python3 flamegraph_analyzer.py "$FOLDED_FILE" --output "$REPORT_FILE"

        success "分析完成！报告已保存到: $REPORT_FILE"
        return 0

    elif [[ -d "$TARGET" ]]; then
        # 目标是目录
        info "分析目录: $TARGET"

        # 根据分析类型搜索文件
        CPU_FOLDED=""
        MEMORY_FOLDED=""

        # 搜索CPU火焰图文件
        if [[ "$ANALYSIS_TYPE" == "cpu" || "$ANALYSIS_TYPE" == "both" ]]; then
            CPU_FOLDED=$(find "$TARGET" -name "*cpu*.folded" -type f | head -1)
            if [[ -z "$CPU_FOLDED" ]]; then
                CPU_FOLDED=$(find "$TARGET" -name "*.folded" -type f | grep -i cpu | head -1)
            fi
        fi

        # 搜索内存火焰图文件
        if [[ "$ANALYSIS_TYPE" == "memory" || "$ANALYSIS_TYPE" == "both" ]]; then
            MEMORY_FOLDED=$(find "$TARGET" -name "*memory*.folded" -type f | head -1)
            if [[ -z "$MEMORY_FOLDED" ]]; then
                MEMORY_FOLDED=$(find "$TARGET" -name "*.folded" -type f | grep -i memory | head -1)
            fi
            if [[ -z "$MEMORY_FOLDED" ]]; then
                MEMORY_FOLDED=$(find "$TARGET" -name "*.folded" -type f | grep -i mem | head -1)
            fi
        fi

        # 检查是否找到文件
        if [[ -z "$CPU_FOLDED" ]] && [[ -z "$MEMORY_FOLDED" ]]; then
            error "在目录中未找到火焰图文件 (.folded)"
            exit 1
        fi

        # 设置项目名称为目录名
        PROJECT_NAME=$(basename "$TARGET")
        if [[ -z "$PROJECT_NAME" ]] || [[ "$PROJECT_NAME" == "." ]]; then
            PROJECT_NAME="folder_analysis"
        fi

        # 创建项目输出子目录
        PROJECT_OUTPUT_DIR="$OUTPUT_DIR/$PROJECT_NAME"
        mkdir -p "$PROJECT_OUTPUT_DIR"

        # 生成时间戳
        TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

        # 分析CPU火焰图
        if [[ -n "$CPU_FOLDED" ]] && [[ -f "$CPU_FOLDED" ]]; then
            info "分析CPU火焰图: $CPU_FOLDED"
            CPU_REPORT="$PROJECT_OUTPUT_DIR/${REPORT_NAME}_cpu_${TIMESTAMP}.txt"
            python3 flamegraph_analyzer.py "$CPU_FOLDED" --output "$CPU_REPORT"
            success "CPU分析完成: $CPU_REPORT"
        elif [[ "$ANALYSIS_TYPE" == "cpu" ]] || [[ "$ANALYSIS_TYPE" == "both" ]]; then
            warning "未找到CPU火焰图文件"
        fi

        # 分析内存火焰图
        if [[ -n "$MEMORY_FOLDED" ]] && [[ -f "$MEMORY_FOLDED" ]]; then
            info "分析内存火焰图: $MEMORY_FOLDED"
            MEMORY_REPORT="$PROJECT_OUTPUT_DIR/${REPORT_NAME}_memory_${TIMESTAMP}.txt"
            python3 flamegraph_analyzer.py "$MEMORY_FOLDED" --output "$MEMORY_REPORT"
            success "内存分析完成: $MEMORY_REPORT"
        elif [[ "$ANALYSIS_TYPE" == "memory" ]] || [[ "$ANALYSIS_TYPE" == "both" ]]; then
            warning "未找到内存火焰图文件"
        fi

        # 生成摘要
        echo ""
        success "分析完成！"
        info "目录: $TARGET"
        info "输出目录: $(realpath "$PROJECT_OUTPUT_DIR")"
        if [[ -f "$CPU_REPORT" ]]; then
            info "CPU分析报告: $(realpath "$CPU_REPORT")"
        fi
        if [[ -f "$MEMORY_REPORT" ]]; then
            info "内存分析报告: $(realpath "$MEMORY_REPORT")"
        fi

        return 0
    else
        # 目标可能是项目名称
        PROJECT_NAME="$TARGET"

        # 检查项目是否在配置中
        if ! grep -q "^  $PROJECT_NAME:" projects.yaml 2>/dev/null; then
            error "项目 '$PROJECT_NAME' 未在 projects.yaml 中找到"
            error "请检查项目名称，或提供有效的文件路径"
            exit 1
        fi

        info "分析项目: $PROJECT_NAME"

        # 创建项目输出子目录
        PROJECT_OUTPUT_DIR="$OUTPUT_DIR/$PROJECT_NAME"
        mkdir -p "$PROJECT_OUTPUT_DIR"

        if [[ "$RUN_PROFILING" == true ]]; then
            # 运行性能分析生成火焰图
            info "运行性能分析生成火焰图..."

            # 构建generic_profiler.py命令
            PROFILER_CMD="python3 generic_profiler.py --project $PROJECT_NAME --time $SAMPLE_TIME"

            if [[ "$ANALYSIS_TYPE" == "cpu" ]]; then
                PROFILER_CMD="$PROFILER_CMD --no-memory"
            fi

            info "执行命令: $PROFILER_CMD"
            eval "$PROFILER_CMD"

            # 检查是否成功生成文件
            PROJECT_CONFIG=$(grep -A 20 "^  $PROJECT_NAME:" projects.yaml | grep "output_dir:" | head -1 | cut -d: -f2 | tr -d ' "')
            if [[ -n "$PROJECT_CONFIG" ]]; then
                # 展开路径中的 ~
                PROJECT_CONFIG="${PROJECT_CONFIG/#\~/$HOME}"
                info "项目输出目录: $PROJECT_CONFIG"
            else
                # 使用默认输出目录结构
                PROJECT_CONFIG="$PROJECT_NAME"
            fi

            # 查找生成的.folded文件
            if [[ -d "$PROJECT_CONFIG" ]]; then
                CPU_FOLDED=$(find "$PROJECT_CONFIG" -name "cpu.folded" -type f | head -1)
                if [[ "$ANALYSIS_TYPE" == "memory" || "$ANALYSIS_TYPE" == "both" ]]; then
                    MEMORY_FOLDED=$(find "$PROJECT_CONFIG" -name "memory.folded" -type f | head -1)
                else
                    MEMORY_FOLDED=""
                fi
            else
                CPU_FOLDED=""
                MEMORY_FOLDED=""
            fi

            if [[ -z "$CPU_FOLDED" ]]; then
                CPU_FOLDED="$PROJECT_CONFIG/cpu.folded"
            fi

            if [[ -z "$MEMORY_FOLDED" ]] && [[ "$ANALYSIS_TYPE" == "memory" || "$ANALYSIS_TYPE" == "both" ]]; then
                MEMORY_FOLDED="$PROJECT_CONFIG/memory.folded"
            fi
        else
            # 不运行性能分析，查找现有文件
            info "查找现有火焰图文件..."

            # 尝试在常见位置查找
            CPU_FOLDED=$(find . -name "*cpu*.folded" -type f | head -1)
            if [[ "$ANALYSIS_TYPE" == "memory" || "$ANALYSIS_TYPE" == "both" ]]; then
                MEMORY_FOLDED=$(find . -name "*memory*.folded" -type f | head -1)
            else
                MEMORY_FOLDED=""
            fi

            if [[ -z "$CPU_FOLDED" ]]; then
                error "未找到CPU火焰图文件 (.folded)"
                exit 1
            fi
        fi

        # 生成时间戳
        TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

        # 分析CPU火焰图
        if [[ -f "$CPU_FOLDED" ]]; then
            info "分析CPU火焰图: $CPU_FOLDED"
            CPU_REPORT="$PROJECT_OUTPUT_DIR/${REPORT_NAME}_cpu_${TIMESTAMP}.txt"
            python3 flamegraph_analyzer.py "$CPU_FOLDED" --output "$CPU_REPORT"
            success "CPU分析完成: $CPU_REPORT"
        else
            warning "未找到CPU火焰图文件: $CPU_FOLDED"
        fi

        # 分析内存火焰图
        if [[ "$ANALYZE_MEMORY" == true ]] && [[ -f "$MEMORY_FOLDED" ]]; then
            info "分析内存火焰图: $MEMORY_FOLDED"
            MEMORY_REPORT="$PROJECT_OUTPUT_DIR/${REPORT_NAME}_memory_${TIMESTAMP}.txt"
            python3 flamegraph_analyzer.py "$MEMORY_FOLDED" --output "$MEMORY_REPORT"
            success "内存分析完成: $MEMORY_REPORT"
        elif [[ "$ANALYZE_MEMORY" == true ]] && [[ ! -f "$MEMORY_FOLDED" ]]; then
            warning "未找到内存火焰图文件: $MEMORY_FOLDED"
        fi

        # 生成摘要
        echo ""
        success "分析完成！"
        info "项目: $PROJECT_NAME"
        info "输出目录: $(realpath "$PROJECT_OUTPUT_DIR")"
        if [[ -f "$CPU_REPORT" ]]; then
            info "CPU分析报告: $(realpath "$CPU_REPORT")"
        fi
        if [[ -f "$MEMORY_REPORT" ]]; then
            info "内存分析报告: $(realpath "$MEMORY_REPORT")"
        fi

        return 0
    fi
}

# 主函数
main() {
    # 解析参数
    parse_arguments "$@"

    # 交互模式
    if [[ "$INTERACTIVE" == true ]]; then
        interactive_mode
    fi

    # 运行分析
    run_analysis

    # 检查是否需要删除旧的分析脚本
    OLD_SCRIPTS=("analyze.py" "leaf_analysis.py" "simple_analyze.py")
    for script in "${OLD_SCRIPTS[@]}"; do
        if [[ -f "$script" ]]; then
            warning "发现旧的分析脚本: $script"
            warning "建议删除旧脚本，因为功能已整合到 flamegraph_analyzer.py"
            warning "如需删除，请运行: rm $script"
        fi
    done

    echo ""
    info "使用以下命令查看报告:"
    if [[ -f "$CPU_REPORT" ]]; then
        echo "  cat $(realpath "$CPU_REPORT") | less"
    fi
    if [[ -f "$MEMORY_REPORT" ]]; then
        echo "  cat $(realpath "$MEMORY_REPORT") | less"
    fi
    if [[ -f "$REPORT_FILE" ]]; then
        echo "  cat $(realpath "$REPORT_FILE") | less"
    fi
}

# 运行主函数
main "$@"