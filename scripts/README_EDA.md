# EDA 模板使用指南

本目录下的 `eda_template.py` 提供了一个快速启动数据探索分析（EDA）的模板脚本。

## 功能特点
- **多格式支持**：自动识别并加载 `.csv` 和 `.xlsx` 文件。
- **数据概览**：快速打印数据集信息、缺失值分布及描述性统计数据。
- **自动可视化**：生成数值列的相关性热图和特征分布直方图。

## 使用步骤

1. **放置数据文件**：
   将你的数据文件（如 `data.csv` 或 `data.xlsx`）放入 `data/` 目录下。

2. **修改配置**：
   打开 `scripts/eda_template.py`，修改文件末尾的 `DATA_PATH` 变量指向你的数据文件路径：
   ```python
   DATA_PATH = "data/your_file.csv"
   ```

3. **运行脚本**：
   在终端执行以下命令：
   ```bash
   python scripts/eda_template.py
   ```

## 依赖要求
请确保已安装以下 Python 库：
- `pandas`
- `numpy`
- `matplotlib`
- `seaborn`
- `openpyxl` (若处理 excel 文件)
