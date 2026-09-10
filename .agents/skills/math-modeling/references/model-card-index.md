# 融合模型卡索引

按 `model-card-contract.md` 改写出售版模型卡。原始出售版目录保持只读；本索引记录生产版参考卡的状态。

## 第一批：直接服务当前路由

| 模型卡 | 路由类别 | 状态 | 需要重点补强 |
|---|---|---|---|
| [TOPSIS](model-card-topsis.md) | 多指标排序 | integrated_with_tests | 正负向、常数列、权重敏感性、秩稳定性 |
| [熵权法](model-card-entropy-weight.md) | 多指标权重 | integrated_with_tests | 零方差、零熵、方向转换和权重解释 |
| [AHP](model-card-ahp.md) | 多指标判断 | integrated_with_tests | 判断矩阵一致性、RI/CR、主观权重敏感性 |
| [灰色关联](model-card-grey-relation.md) | 关联排序 | integrated_with_tests | 参考序列、分辨系数、归一化和解释边界 |
| [GM(1,1)](model-card-gm11.md) | 小样本单序列预测 | integrated_with_tests | 序列限制、滚动验证、外推风险和残差 |
| [回归预测](model-card-regression.md) | 连续数值样本外预测 | integrated_with_tests | 泄漏、切分、基线、测试误差和预测边界 |
| [OLS 统计推断与诊断](model-card-ols-diagnostics.md) | 连续响应条件关联/统计推断 | integrated_with_tests | 协方差预声明、假设诊断、共线性、影响点和因果边界 |
| [单变量曲线分析](model-card-curve-analysis.md) | 插值域曲线比较/条件区间 | integrated_with_tests | 开发集选型、独立测试、残差、参数/响应/预测区间和外推边界 |
| [时间序列基线](model-card-time-series.md) | 时间依赖预测 | integrated_with_tests | 时间顺序、滚动验证、窗口和零值指标 |
| [线性规划](model-card-linear-programming.md) | 线性资源分配 | integrated_with_tests | 单位、可行性、约束残差和对偶/边界解释 |
| [整数与混合整数规划](model-card-integer-programming.md) | 离散决策 | integrated_with_tests | 整数可行性、LP 松弛、求解状态、最优性缺口和规模 |
| [Monte Carlo](model-card-monte-carlo.md) | 随机情景/不确定性 | integrated_with_tests | 分布来源、独立性、种子、收敛、区间含义和重复运行 |
| [M/M/1 排队模型](model-card-queueing.md) | 服务系统/等待 | integrated_with_tests | 稳定性、暖机、时间平均、Little 定律、理论对照和独立重复 |
| [连续非线性优化](model-card-nonlinear-optimization.md) | 非线性决策 | integrated_with_tests | 有限边界、表达式安全、多起点、局部最优和约束复算 |
| [带约束多目标优化](model-card-multi-objective-optimization.md) | 多目标连续决策 | integrated_with_tests | 参考前沿、独立可行/非支配复算、多种子稳定性、尺度和偏好敏感性 |
| [图与网络](model-card-graph-network.md) | 最短路/最大流 | integrated_with_tests | 边语义、方向、路径成本复算、容量、流守恒和最大流最小割一致性 |
| [常微分方程初值问题](model-card-ode-system.md) | ODE/连续动力学 | integrated_with_tests | 初值、单位、守恒/解析参考、容差和最大步长敏感性、结构边界 |
| [二分类](model-card-classification.md) | 类别预测 | integrated_with_tests | 类别不平衡、训练侧校准、阈值、组泄漏和概率指标 |
| [KMeans 聚类](model-card-clustering.md) | 无监督分组 | integrated_with_tests | 标准化、候选簇数、重复稳定性、簇画像和解释边界 |
| [PCA](model-card-pca.md) | 线性降维/共线结构诊断 | integrated_with_tests | 方差解释、尺度影响、载荷解释、重构误差和信息损失 |

## 第二批：扩展类别

| 模型卡 | 路由类别 | 状态 | 需要重点补强 |
|---|---|---|---|
| DBSCAN | 非凸/含噪声聚类 | planned | 邻域尺度、噪声点、参数敏感性和稳定性 |

## 改写顺序

第一批评价、预测、OLS 统计推断、单变量曲线分析、单目标/多目标优化、图网络、ODE 连续动力学、分类、KMeans 和 PCA 卡已接入对应脚本；扩展模型继续逐项处理。每完成一张卡，必须补一个最小可运行验证案例或明确 `not_applicable` 的原因。预测回归与 OLS 推断是两条独立路由，不得用训练内诊断替代样本外验证，也不得用留出预测指标替代系数推断。
