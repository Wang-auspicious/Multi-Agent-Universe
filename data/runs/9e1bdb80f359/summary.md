已为您创建 `eda_module.py` 文件，内容如下：

```python
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt

class EDAModule:
    def __init__(self, df: pd.DataFrame):
        self.df = df

    def basic_info(self):
        print("--- 数据集维度 ---")
        print(self.df.shape)
        print("\n--- 缺失值统计 ---")
        print(self.df.isnull().sum())
        print("\n--- 描述性统计 ---")
        print(self.df.describe())

    def plot_distributions(self):
        numerical_cols = self.df.select_dtypes(include=['number']).columns
        for col in numerical_cols:
            plt.figure(figsize=(8, 4))
            sns.histplot(self.df[col], kde=True)
            plt.title(f"Distribution of {col}")
            plt.show()

    def plot_correlation(self):
        plt.figure(figsize=(10, 8))
        sns.heatmap(self.df.corr(numeric_only=True), annot=True, cmap='coolwarm')
        plt.title("Correlation Heatmap")
        plt.show()

    def run_full_report(self):
        self.basic_info()
        self.plot_distributions()
        self.plot_correlation()
```

**变更说明：**
1. **新增文件**：在项目中创建了 `eda_module.py`，封装了基础统计、分布绘图及相关性分析功能。
2. **代码逻辑**：使用了 `pandas` 进行数据处理，结合 `seaborn` 和 `matplotlib` 实现可视化，支持自动识别数值型特征。