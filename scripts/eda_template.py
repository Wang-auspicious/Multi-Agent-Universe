import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

# 设置可视化风格
sns.set(style="whitegrid")

def load_data(file_path):
    """加载数据"""
    try:
        if file_path.endswith('.csv'):
            return pd.read_csv(file_path)
        elif file_path.endswith('.xlsx'):
            return pd.read_excel(file_path)
        else:
            raise ValueError("Unsupported file format")
    except Exception as e:
        print(f"Error loading data: {e}")
        return None

def basic_eda(df):
    """执行基础探索性数据分析"""
    print("--- 数据基本信息 ---")
    print(df.info())
    
    print("\n--- 缺失值统计 ---")
    print(df.isnull().sum())
    
    print("\n--- 描述性统计 ---")
    print(df.describe())

def plot_visualizations(df):
    """生成基础可视化图表"""
    # 数值列相关性热图
    numeric_df = df.select_dtypes(include=[np.number])
    if not numeric_df.empty:
        plt.figure(figsize=(10, 8))
        sns.heatmap(numeric_df.corr(), annot=True, cmap='coolwarm', fmt='.2f')
        plt.title("Correlation Heatmap")
        plt.show()

    # 数值列分布直方图
    df.hist(figsize=(12, 10), bins=20)
    plt.tight_layout()
    plt.show()

def main(file_path):
    df = load_data(file_path)
    if df is not None:
        basic_eda(df)
        plot_visualizations(df)

if __name__ == "__main__":
    # 在此处替换你的数据文件路径
    DATA_PATH = "data/sample.csv"
    main(DATA_PATH)