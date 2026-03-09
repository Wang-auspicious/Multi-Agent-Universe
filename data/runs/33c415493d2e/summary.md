您好，这是一个通用的数据分析 EDA（探索性数据分析）模板。由于未直接生成文件，请参考下方的代码块进行使用：

### EDA 模板代码
您可以将以下内容保存为 `eda_template.py`：

```python
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

# 设置绘图风格
sns.set(style="whitegrid")

def run_eda(df):
    # 1. 数据基础信息概览
    print("--- 1. 数据概览 ---")
    print(f"行数: {df.shape[0]}, 列数: {df.shape[1]}")
    print(df.info())

    # 2. 缺失值检查
    print("\n--- 2. 缺失值检查 ---")
    missing = df.isnull().sum()
    print(missing[missing > 0])

    # 3. 数值特征描述性统计
    print("\n--- 3. 数值特征统计摘要 ---")
    print(df.describe())

    # 4. 可视化分析
    # 绘制数值列分布图
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    for col in numeric_cols:
        plt.figure(figsize=(8, 4))
        sns.histplot(df[col].dropna(), kde=True)
        plt.title(f'Distribution of {col}')
        plt.show()

    # 绘制相关性热力图
    plt.figure(figsize=(10, 8))
    sns.heatmap(df.corr(numeric_only=True), annot=True, cmap='coolwarm', fmt='.2f')
    plt.title('Correlation Heatmap')
    plt.show()
```

### 使用建议
1. **调用方式**：在您的主程序中导入该函数，传入 DataFrame 即可：
   ```python
   from eda_template import run_eda
   df = pd.read_csv('your_data.csv')
   run_eda(df)
   ```
2. **预处理**：在调用 `run_eda` 之前，建议先处理数据类型（如转换日期格式）或根据业务需求填充关键缺失值。
3. **扩展性**：该模板涵盖了基础的分布和相关性分析，您可以根据项目需求在 `run_eda` 中补充箱线图（检测异常值）或分类统计图。