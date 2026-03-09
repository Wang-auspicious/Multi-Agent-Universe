import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import scipy.stats as stats

class EDAProcessor:
    def __init__(self, df):
        self.df = df

    def basic_info(self):
        print(self.df.info())
        print(self.df.describe(include='all'))
        print(self.df.isnull().sum())
        print(self.df.duplicated().sum())

    def univariate_analysis(self, column):
        if self.df[column].dtype in ['int64', 'float64']:
            fig, axes = plt.subplots(1, 2, figsize=(12, 4))
            sns.histplot(self.df[column], kde=True, ax=axes[0])
            sns.boxplot(x=self.df[column], ax=axes[1])
            plt.show()
        else:
            sns.countplot(x=self.df[column])
            plt.xticks(rotation=45)
            plt.show()

    def bivariate_analysis(self, col1, col2):
        if self.df[col1].dtype in ['int64', 'float64'] and self.df[col2].dtype in ['int64', 'float64']:
            sns.scatterplot(x=col1, y=col2, data=self.df)
        elif self.df[col1].dtype in ['int64', 'float64']:
            sns.boxplot(x=col2, y=col1, data=self.df)
        else:
            sns.heatmap(pd.crosstab(self.df[col1], self.df[col2]), annot=True, fmt='d')
        plt.show()

    def correlation_matrix(self):
        numeric_df = self.df.select_dtypes(include=[np.number])
        plt.figure(figsize=(10, 8))
        sns.heatmap(numeric_df.corr(), annot=True, cmap='coolwarm', fmt='.2f')
        plt.show()

    def outlier_detection(self, column, threshold=1.5):
        Q1 = self.df[column].quantile(0.25)
        Q3 = self.df[column].quantile(0.75)
        IQR = Q3 - Q1
        outliers = self.df[(self.df[column] < Q1 - threshold * IQR) | (self.df[column] > Q3 + threshold * IQR)]
        return outliers

    def missing_value_treatment(self, method='mean'):
        if method == 'mean':
            self.df.fillna(self.df.mean(numeric_only=True), inplace=True)
        elif method == 'median':
            self.df.fillna(self.df.median(numeric_only=True), inplace=True)
        elif method == 'drop':
            self.df.dropna(inplace=True)

    def save_summary(self, filename='eda_report.txt'):
        with open(filename, 'w') as f:
            f.write(str(self.df.describe()))
            f.write("\n\nMissing Values:\n")
            f.write(str(self.df.isnull().sum()))
