# 项目详细介绍与执行计划

## Counterfactual Trace Auditing (CTA): 面向 Agent Skill 的行为审计框架

## 第一部分：项目背景与动机

### 1.1 Agent Skill 的兴起与问题

Agent skill 是一种结构化的 markdown 文档，编码了领域程序性知识（标准操作流程、代码模板、领域规范），在推理时注入 LLM agent 的 context window 作为参考文档。与 fine-tuning 和 RAG 不同，skill injection 不需要修改模型参数或搭建外部检索管线，仅需将 SKILL.md 文件放置在项目目录中，agent 自动发现并使用。

这一生态增长极快。根据 SkillsBench (Li et al., 2026) 的统计，在 136 天内共有 84,192 个 skill 被创建。Anthropic 在 2025 年正式推出 "Agent Skills" 功能，Claude Code 原生支持 skill 的自动发现和加载。

然而，SWE-Skills-Bench (Han et al., 2026) 的实证研究揭示了一个严峻的现实：

- **49 个被评估的 SWE skill 中，39 个（80%）的 pass rate 改善为零**
- **平均 pass rate 改善仅为 +1.2%**
- **7 个 skill 产生了正向效果（最高 +30%）**
- **3 个 skill 反而降低了性能（最高 -10%），原因是 skill 中的版本特定模板与目标项目发生冲突**
- **Token 开销与性能增益完全解耦：部分零改善的 skill 导致了高达 451% 的 token 消耗增加**

这些发现表明：skill injection 并非"免费的午餐"，而是一种具有结构性风险的干预措施。

### 1.2 当前评估范式的缺陷

现有评估（包括 SWE-Skills-Bench 和 SkillsBench）采用 **input-output 级别的黑盒评估**：给定任务，分别在 with-skill 和 without-skill 条件下运行 agent，比较最终的 pass/fail 结果。这种方法可以回答"skill 是否有用"，但无法回答：

1. **Skill 如何改变了 agent 的中间行为？** Agent 在有 skill 时读了哪些不同的文件，生成了哪些不同的代码，遇到了哪些不同的错误？
2. **哪些行为变化导致了结果差异？** 在最终 pass/fail 不同的情况下，是哪一步的 divergence 导致了成功或失败？
3. **能否在执行前预测 skill 的效用？** 给定一个 skill 文档和一个目标项目，能否基于静态特征判断这个 skill 是否值得注入？

这类似于药物评估只看存活率而不做药理学分析---足够做 go/no-go 决策，但不足以改进 skill 设计、预测失败模式或建立部署时的安全保障。

---

## 第二部分：技术方案

> **关于标注资源的说明**：本项目无人工众包标注预算，全流程采用 **LLM-as-annotator** 方案（GPT-5 + Claude Sonnet 4.5 多 judge 集成），并以作者团队亲自标注的小规模 gold set（~30 样本/任务）做校准。该范式参考 Gilardi et al. (2023) 的发现——在结构化分类任务上 LLM 标注与众包标注相当甚至更优。所有依赖标注的环节（§2.3.3 phase 验证、§2.4.1 intent 提取、§2.5.1 SIP 标注）均采用此方案，详见各小节。

### 2.1 整体框架

CTA 框架包含五个模块，形成完整的审计管线：

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    Counterfactual Trace Auditing (CTA) Pipeline                  │
│                                                                                 │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐     │
│  │ Module 1 │   │ Module 2 │   │ Module 3 │   │ Module 4 │   │ Module 5 │     │
│  │  Trace   │──▸│  Phase   │──▸│  Trace   │──▸│ SIP Det- │──▸│  Skill   │     │
│  │Collection│   │  Segmen- │   │Alignment │   │ection &  │   │ Quality  │     │
│  │& Parsing │   │  tation  │   │& Diverg. │   │ Outcome  │   │Prediction│     │
│  └──────────┘   └──────────┘   └──────────┘   │ Analysis │   └──────────┘     │
│                                                └──────────┘                     │
│  Input: Paired   Output:        Output:        Output:        Output:           │
│  traces τ+, τ-   Phased traces  Divergence     SIP labels,    Pre-deployment    │
│                                  records        β coefficients skill score       │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Module 1: Trace Collection and Parsing

#### 2.2.1 Trace 表示

每条执行 trace 表示为事件序列 $\tau = (e_1, e_2, \ldots, e_T)$，每个事件是一个结构化元组：

```
Event = {
    event_id:     int,           # 事件序号
    type:         enum,          # read | write | execute | search | reason | error | tool_call
    target:       string,        # 操作对象（文件路径、命令字符串、工具名）
    content:      string,        # 具体内容（读取的文件内容、生成的 diff、命令输出）
    reasoning:    string,        # Agent 在该步骤前的自然语言推理
    outcome:      enum,          # success | failure | partial
    token_count:  int,           # 该步骤消耗的 token 数
    timestamp:    float          # 时间戳
}
```

#### 2.2.2 数据源

Claude Code 产生结构化的 conversation log，其中交替包含 reasoning text 和 tool use blocks。每个 tool use block 对应一个 tool call（bash、read_file、write_file 等），包含 input parameters 和 output results。

我们编写一个 trace parser，从 Claude Code 的 JSON conversation log 中提取事件序列。具体解析规则：

- 每个 `tool_use` block 映射为一个 event，type 根据 tool name 确定（`bash` → `execute`，`Read` → `read`，`Write` → `write` 等）
- 两个相邻 tool calls 之间的 reasoning text 聚合到后一个 event 的 `reasoning` 字段
- `execute` 类型的 event 的 `outcome` 根据返回码确定（exit code 0 → success，非零 → failure）
- `write` 类型的 event 的 `content` 存储实际的文件 diff（通过比较写入前后的文件内容生成）

#### 2.2.3 数据规模

基于 SWE-Skills-Bench 的 49 个 skills 和 565 个 task instances：

- 每个 task instance 在 with-skill 和 without-skill 两个条件下各运行 3 次
- 总运行次数：$565 \times 2 \times 3 = 3{,}390$
- 主分析使用 temperature=0（确定性 trace），variance estimation 使用 temperature=0.7
- 预估每条 trace 包含 20-100 个 events，总 events 数量在 67K-339K 之间

### 2.3 Module 2: Phase Segmentation

#### 2.3.1 Phase 定义

将每条 trace 划分为六个规范化的 SWE 阶段：

| Phase | 定义 | 典型事件模式 |
|-------|------|------------|
| **Orientation** | Agent 了解项目结构和依赖 | 连续的 `read` events（README、配置文件、目录结构） |
| **Planning** | Agent 制定实现策略 | `reason` events 包含策略性语言（"I will"、"The approach is"、"Steps:"） |
| **Implementation** | Agent 编写代码或配置 | `write` events（创建/修改源文件） |
| **Validation** | Agent 运行测试或构建 | `execute` events（pytest、npm test、make 等） |
| **Debugging** | Agent 处理错误并修复 | error-triggered 循环：`execute`(fail) → `read` → `reason` → `write` → `execute` |
| **Finalization** | Agent 做最终调整和清理 | 末尾的 `write` events，无后续 `execute` |

#### 2.3.2 分割算法

采用基于规则的有限状态机 (FSM)。状态转移规则：

```
INIT → Orientation:     on first read event
Orientation → Planning:  on reason event with planning keywords
Planning → Implementation: on first write event after Planning
Implementation → Validation: on execute event with test/build command
Validation → Debugging:  on execute(failure) event
Debugging → Implementation: on write event after error handling
Validation → Finalization: on write event after all tests pass
```

允许循环：Implementation ↔ Validation ↔ Debugging 可以多次迭代。

#### 2.3.3 验证

由于无人工标注资源，采用 **LLM-as-annotator** 方案：从 565 个 task instance 中分层抽样 50 条 trace，使用 GPT-5 (作为 strong reference annotator) 对每条 trace 中的每个 event 标注其所属 phase。Prompt 中提供 §2.3.1 的 phase 定义和典型事件模式作为 rubric，并给出 3-shot in-context 示例。

为缓解单一模型的系统性偏差，使用两套独立配置的 LLM judge：
- **Judge A**: GPT-5, temperature=0, prompt 强调"基于 event 类型 + 关键词匹配"
- **Judge B**: GPT-5, temperature=0.3, prompt 强调"基于上下文语义和 agent 意图"

将两个 judge 一致同意的 phase boundary 作为 silver-standard reference，在该 reference 上验证 FSM 分割器的 $F_1$ score。同时报告两个 LLM judge 之间的 phase 标注 Cohen's κ 作为标注质量的下界估计（$\kappa > 0.6$ 视为可接受）。

目标：phase boundary $F_1 > 0.80$（相比原计划 0.85 略放宽，因 silver-standard 本身存在噪声）。如果规则方法不达标，退化为只使用 Orientation / Implementation / Validation 三个粗粒度 phase。

此外，作者团队对其中 10 条 trace 进行 spot-check（仅用于发现 LLM judge 的系统性错误，不作为训练/评估数据），如发现问题修订 prompt 后重新标注。

### 2.4 Module 3: Trace Alignment and Divergence Detection

这是 CTA 框架的核心技术贡献，也是与 SUVA 的根本区别所在。

#### 2.4.1 两级对齐策略

**第一级：Phase 对齐。** 将 $\tau^+$ 和 $\tau^-$ 的 phase 序列进行对齐。由于两条 trace 的 phase 数量和顺序可能不同（例如 with-skill 的 agent 可能跳过了 Debugging phase，或多了一轮 Implementation-Validation 循环），我们使用动态时间规整 (DTW) 在 phase 级别进行对齐。Phase 之间的距离函数定义为：

$$d(\text{phase}_i^+, \text{phase}_j^-) = \begin{cases} 0 & \text{if same phase type} \\ 1 & \text{if different phase types} \end{cases}$$

**第二级：Intent 对齐（phase 内部）。** 在每对对齐的 phase 中，提取 "intents"。一个 intent 是 agent 在 reasoning text 中表达的一个子目标。例如：

- "I need to create the Server CRD with the correct API version"
- "Let me run the tests to check if the configuration is valid"
- "The error is in the port specification, I will fix it"

Intent 提取方法：**采用 LLM-based zero-shot extraction，无需 fine-tune**。对每段 reasoning text 调用 GPT-5（temperature=0），prompt 要求模型抽取 1-N 个 intent spans 并返回结构化 JSON：

```json
{"intents": [{"span": "...", "start_char": int, "end_char": int, "category": "create|read|run|fix|verify|other"}]}
```

Prompt 中提供 5-shot in-context 示例（覆盖典型 SWE 场景）以稳定输出格式。两个 intents 的相似度通过 sentence embedding（`all-MiniLM-L6-v2`）的 cosine similarity 衡量。

**对齐阈值校准（无人工标注情形）：** $\delta$ 不再依赖 annotated set，而是采用 **unsupervised heuristic**：
1. 从全部 trace 中抽样 500 对 (intent$^+$, intent$^-$)，计算 cosine similarity 分布
2. 设 $\delta$ 为分布的 75-th percentile（即对齐倾向于高相似度对）
3. 同时报告 $\delta \in \{0.5, 0.6, 0.7, 0.8\}$ 下的 sensitivity analysis，验证最终结论的稳健性
4. 用 GPT-5 作为"对齐判官"在 100 个边界 case (similarity ∈ [0.4, 0.7]) 上判断是否真正对齐，作为校准辅助信号

#### 2.4.2 Divergence Record

对于每对对齐的 intent，比较后续的 action sequences，记录 divergence：

```
DivergenceRecord = {
    divergence_id:  int,
    intent_pair:    (intent+, intent-),     # 对齐的 intent 对
    phase:          string,                  # 所在 phase
    actions_plus:   [Event],                 # with-skill 条件下的后续 actions
    actions_minus:  [Event],                 # without-skill 条件下的后续 actions
    divergence_type: enum,                   # target_mismatch | content_mismatch | outcome_mismatch
    skill_region:   string,                  # Skill 文档中与该 divergence 最相似的区域
    skill_similarity: float                  # 该区域与 divergence 内容的相似度
}
```

`skill_region` 的计算方法：将 skill 文档按 section 划分，对每个 divergence 中 with-skill action 的 content，找到 skill 文档中 cosine similarity 最高的 section。这建立了从 divergence 到 skill 内容的可追溯性。

#### 2.4.3 Divergence 特征化

对于每个 task instance $i$，从所有 divergence records 中提取以下统计特征：

- **Divergence count**：$\tau_i^+$ 和 $\tau_i^-$ 之间的总 divergence 数量
- **Phase distribution**：各 phase 中 divergence 的分布
- **First divergence position**：首个 divergence 出现在 trace 中的相对位置（0-1）
- **Skill similarity distribution**：所有 divergences 的 skill_similarity 的均值和方差
- **Target overlap**：$\tau_i^+$ 和 $\tau_i^-$ 操作的文件集合的 Jaccard 相似度
- **Code structural distance**：对 write events 中的代码 diff，计算 AST 编辑距离

### 2.5 Module 4: Skill Influence Pattern Detection and Outcome Analysis

#### 2.5.1 SIP 分类体系构建

由于无人工标注资源，采用 **LLM-as-annotator + 作者小规模 gold set 校准** 的两阶段方法。该范式参考了 Gilardi et al. (2023, *PNAS*) "ChatGPT Outperforms Crowd Workers for Text-Annotation Tasks" 的发现：在结构化分类任务上，LLM 标注的可靠性已可与众包标注相当甚至更优。

**Stage 1: LLM-driven open coding（数据驱动归纳）**

选取 200 个 divergence records（相比原 100 翻倍，因 LLM 标注边际成本接近零）。样本分层抽取：
- 80 个来自 $\Delta P > 0$ 的 skills
- 80 个来自 $\Delta P = 0$ 的 skills
- 40 个来自 $\Delta P < 0$ 的 skills

**多 judge 集成标注协议（模拟"多标注者"）**：使用三个独立配置的 LLM judge 对每个 divergence 独立打标：

| Judge | 模型 | 配置 | 角色定位 |
|-------|------|------|---------|
| Judge-A | GPT-5 | temp=0；prompt 强调 evidence-grounded | "保守派" |
| Judge-B | GPT-5 | temp=0.5；prompt 强调 mechanism analysis | "分析派" |
| Judge-C | Claude Sonnet 4.5 | temp=0；跨厂商模型避免 model-family bias | "对照派" |

每个 judge 接收同一个 divergence record（含 intent_pair、actions_plus、actions_minus、skill_region），按结构化 prompt 输出：

```json
{
  "skill_role": "guidance|interference|irrelevant",
  "behavior_change": "path|content|error_handling|none",
  "outcome_impact": "positive|neutral|negative",
  "matched_sip_categories": ["PS","EP","RE","SA","CB"],
  "evidence_quote": "直接引用 trace 中支持判断的片段",
  "rationale": "..."
}
```

**Inter-LLM Agreement 评估**：在三个 judge 的标注上计算 Fleiss' κ（多评估者扩展 kappa），目标 $\kappa > 0.6$（LLM-as-annotator 文献中 $\kappa \in [0.5, 0.7]$ 为常见可接受区间）。

**最终标签合成**：采用 **majority voting**；当三方完全分歧时（预计 10–20% 样本），调用 GPT-5 reconciliation prompt 在看到三方理由后做最终裁决。

**Stage 1.5: 作者 Gold Set 校准（可承担的人工工作量）**

为验证 LLM 标注可信度，作者团队亲自标注 **30 个 divergence**（约 3 小时/人）作为 gold set：
- 报告 LLM 集成标注 vs gold set 的 agreement（accuracy + per-class F1 + κ）
- 若 agreement < 0.70，迭代修订 prompt 后对全部 200 个样本重新标注
- 该 gold set **不**进入下游分类器训练集，仅用于 prompt validation 和论文中的 "annotation quality" 章节

**Stage 2: 理论整合**

将 LLM 标注归纳出的类别与以下文献中的已知现象对照：
- In-context learning 文献中的 anchoring/priming effects (Zhao et al., 2021)
- Prompt engineering 中的 instruction following pathologies (Wei et al., 2023)
- 软件工程中的 template-driven development 的利弊 (Gamma et al., 1994)
- SWE-Skills-Bench 中已识别的三种失败模式（surface anchoring、hallucination、concept bleed）

最终形成一个经过理论对照验证的 SIP 分类体系。

**精简后的 5 类 SIP 分类体系**（v2，相比初版 v1 的 8 类做出如下调整）：

> **设计原则**：每个保留的 SIP 必须满足 (1) 有明确理论基础、(2) 在 SWE 场景下可观测、(3) LLM judge 可靠区分边界。基于 pilot 数据（49 个 task）观察到 PS/CN/PE/SA/CD 5 类均零检测，分析后确认 CN 与 PS 边界模糊、CD 工程上难落地、PE 与 RR 在 SWE 中本质同质，故合并/删除。详见 §2.5.2 ablation。

**Constructive SIPs（建设性影响模式）：**

| SIP | 定义 | 典型表现 | 预期检测信号 |
|-----|------|---------|------------|
| **Procedural Scaffolding (PS)** | Skill 提供了 agent 参数化知识中不包含的步骤序列或公式 | Agent 在 with-skill 时按 skill 的步骤执行，在 without-skill 时缺失关键步骤；典型如金融公式、协议握手流程 | (1) with-skill phase 序列与 skill 文档中 step section 高度对齐；(2) 关键 implementation event 的 reasoning 显式引用 skill 步骤；(3) without-skill 缺失对应步骤导致 outcome failure |
| **Edge-case Prompting (EP)** | Skill 作为 checklist 提醒 agent 注意易遗漏的边界情况 | Agent 在 with-skill 时处理了额外的边界情况（null check、版本兼容、异常分支） | (1) with-skill 的 write events 包含额外的 if/try/assert 分支；(2) 额外 write 的 target 在 without-skill 中也存在但 content 缺少边界处理；(3) skill 文档显式列出该边界 case |

**Neutral SIPs（中性影响模式）：**

| SIP | 定义 | 典型表现 | 预期检测信号 |
|-----|------|---------|------------|
| **Redundant Exploration (RE)** *(合并自 RR + PE)* | Skill 内容与 agent 已有知识重复，或诱导 agent 探索后回到相同解 | Agent 在 reasoning 中提及 skill 但最终 action 与 without-skill 基本等价；可能多了几轮无效 Implementation-Validation 循环 | (1) 高 intent similarity (>0.8) 但 action count 不必相同；(2) 最终 code diff 的 AST 距离 < 阈值；(3) with-skill token 消耗显著高于 without-skill 但 outcome 相同 |

**Destructive SIPs（破坏性影响模式）：**

| SIP | 定义 | 典型表现 | 预期检测信号 |
|-----|------|---------|------------|
| **Surface Anchoring (SA)** | Agent 逐字复制 skill 模板中的具体值（版本号、API 参数、import 路径） | 生成代码中的 literal token 与 skill template 完全匹配但与目标项目不兼容；典型如 SWE-Skills-Bench 中 `springboot-tdd`、`linkerd-patterns` 案例 | (1) skill 中的 literal n-gram (n>=3，含版本号/路径/常量) 在 with-skill 的 write event content 中精确出现；(2) without-skill 不出现该 literal；(3) 该 literal 与目标项目实际 dependency / config 不匹配（可由 baseline failure 佐证） |
| **Concept Bleed (CB)** | Skill 的广泛覆盖导致 agent 混淆相关但不同的概念，引入 task 未要求的内容 | Agent 生成了 task 未要求的额外资源/配置/文件 | (1) write events 数量显著增加；(2) 新增 target 不在 requirement 的 File Operations 列表中；(3) 新增内容与 skill 中**非任务相关章节**的 cosine similarity 高 |

**已弃用的 SIP**（v1 → v2 的删减说明，论文 ablation 章节中讨论）：

| 弃用 SIP | 弃用理由 |
|---------|--------|
| **Constraint Narrowing (CN)** | 与 PS 在 SWE 场景下边界模糊（PS = "skill 提供步骤"，CN = "skill 排除错误选项"），LLM judge 在 pilot 上无法稳定区分；功能性观察被 PS 覆盖 |
| **Parallel Exploration (PE)** | 与 RR 同质，均表现为"高 token、低 outcome 影响"；合并入 RE 后保持中性类的统计独立性 |
| **Context Displacement (CD)** | 需要测量 context window 中的 skill 占用 vs requirement 漏失，工程上需要 token-level attribution，超出当前 trace parsing 能力；改由 §2.6 中的 `document_length` 特征间接捕捉 |

#### 2.5.2 自动化 SIP 分类器

基于 §2.5.1 的 **200 个 LLM 标注 divergence records**（majority-voted labels），训练一个 multi-label classifier，用于将分类能力扩展到全部 ~3K divergence。

**两路径并行 + 横向比较**（重点：避免完全依赖 LLM 标签可能引入的循环偏差）：

**Path A — 蒸馏型分类器（cheap & fast）**：

- **输入特征：**
  - Divergence record 的结构化特征（divergence_type、phase、skill_similarity）
  - Intent pair 的语义特征（sentence embedding，`all-MiniLM-L6-v2`）
  - Action sequence 的统计特征（event count、type distribution、error rate）
  - Skill region 的文本特征（是否包含代码模板、版本号、具体参数）
- **模型：** XGBoost（multi-label via one-vs-rest），因 200 样本仍偏小，避免使用大型神经网络
- **评估：** 5-fold CV on the 200 LLM-annotated divergences；目标 macro $F_1 > 0.70$
- **额外评估：** 在 30 个作者 gold set 上报告 out-of-distribution 性能（验证分类器是否仅在拟合 LLM 偏差）

**Path B — 直接 LLM-as-classifier（cheap & no training）**：

- 在推理时对每个 divergence 直接调用 GPT-5（zero-shot 或 few-shot），输出 SIP 多标签
- 在 200 个 divergence 的 5-fold 设置下报告自身性能；同时在 30 个 gold set 上报告
- 与 Path A 比较：若 Path B 性能显著优于 Path A，说明 SIP 检测本质上是语义任务，蒸馏损失大；论文中保留 Path B 作为 production 方案
- **成本控制：** 全部 ~3K divergence 分类的预算上限设为 \$50（GPT-5 batch API + prompt caching）

**最终选择：** 在 gold set 上 macro F1 更高的路径作为 §2.5.3 下游分析的输入；同时在论文中报告两路径的差异作为 ablation。

#### 2.5.3 Divergence-Outcome 依赖分析

对全部 565 个 task instances 运行自动化 SIP 分类器，得到每个 instance 的 SIP 特征向量：

$$\mathbf{D}_i = [d_i^{\text{PS}}, d_i^{\text{EP}}, d_i^{\text{RE}}, d_i^{\text{SA}}, d_i^{\text{CB}}]$$

**模型 1：Outcome change prediction**

$$P(\texttt{pass}_i^+ \neq \texttt{pass}_i^- \mid \mathbf{D}_i, \mathbf{S}_i, \mathbf{R}_i) = \sigma(\boldsymbol{\beta}^\top \mathbf{D}_i + \boldsymbol{\gamma}^\top \mathbf{S}_i + \boldsymbol{\eta}^\top \mathbf{R}_i)$$

其中 $\mathbf{S}_i$ 是 skill-level 特征，$\mathbf{R}_i$ 是 project-level 特征。$\boldsymbol{\beta}$ 系数量化每种 SIP 与 outcome change 的关联强度。

**模型 2：Change direction prediction（条件于 change 发生）**

$$P(\texttt{pass}_i^+ > \texttt{pass}_i^- \mid \texttt{pass}_i^+ \neq \texttt{pass}_i^-, \mathbf{D}_i) = \sigma(\boldsymbol{\alpha}^\top \mathbf{D}_i)$$

$\boldsymbol{\alpha}$ 系数区分建设性 SIPs 和破坏性 SIPs 的方向性效应。

**与 SUVA 的类比：** SUVA 的 $\boldsymbol{\phi}$ 系数量化 "CoT 中提及 fairness → 选择 prosocial action 的概率增加多少"。CTA 的 $\boldsymbol{\beta}$ 系数量化 "trace 中出现 surface anchoring → task outcome 改变的概率增加多少"。两者都建立了中间过程与最终结果之间的统计关联，但分析对象和分类体系完全不同。

### 2.6 Module 5: Predictive Skill Quality Assessment

#### 2.6.1 特征工程

**Skill 文档特征 ($\mathbf{S}$)：**

| 特征 | 计算方法 | 直觉 |
|------|---------|------|
| Template specificity | 包含硬编码值（版本号、IP、端口）的行数占比 | 高 specificity → 高 SA 风险 |
| Abstraction level | placeholder/variable 引用占比 | 高 abstraction → 低 SA 风险 |
| Coverage breadth | Heading 数量 × topic diversity (LDA) | 高 breadth → 高 CB 风险 |
| Document length | Token count | 长文档 → 高 CD 风险 |
| Code-to-prose ratio | 代码块 token / 总 token | 高 code ratio → 高 SA 风险（更多可复制的模板） |
| Instruction density | 命令句（"Use X"、"Do not Y"）的密度 | 高密度 → 更强的 CN 效应 |

**Project 特征 ($\mathbf{R}$)：**

| 特征 | 计算方法 | 直觉 |
|------|---------|------|
| Tech stack match | Skill 提及技术名称 ∩ project 依赖列表 的 Jaccard 系数 | 低匹配 → skill 可能无关或有害 |
| Version alignment | Skill 中硬编码版本号与 project 实际版本的匹配度 | 不匹配 → 高 SA 风险 |
| Project complexity | 文件数 + LOC + 依赖数 | 复杂项目可能更受益于 skill |
| Baseline difficulty | Without-skill pass rate | 高 baseline → skill 难以提供额外帮助 |

**交互特征 ($\mathbf{S} \times \mathbf{R}$)：**

| 特征 | 计算方法 |
|------|---------|
| Semantic relevance | Skill 文档 embedding 与 project README embedding 的 cosine similarity |
| API overlap | Skill 中提到的 API 在 project codebase 中出现的比例 |
| Specificity-complexity ratio | Template specificity / project complexity（衡量 skill 模板相对项目的"刚性"程度） |

#### 2.6.2 预测模型

**训练策略：** Leave-one-skill-out cross-validation。对 49 个 skills 中的每一个：用其余 48 个 skills 的所有 instances 训练模型，在 held-out skill 的所有 instances 上预测。

**预测目标：** 分类问题——预测 skill utility 类别（positive / neutral / negative）。

**模型：** XGBoost（与 SUVA 的 internal consistency check 中使用的模型一致），通过 grid search 调参。

**评估指标：**
- 三分类 accuracy 和 macro $F_1$
- 重点关注 negative class 的 recall（能否正确识别出有害的 skills）
- 与 baselines 的比较（random、skill length only、semantic similarity only、SUVA-adapted）

---

## 第三部分：实验设计

### 3.1 研究问题

**RQ1（行为特征化）：** Skill injection 在 agent 执行 trace 中产生了哪些类型的行为变化？不同 SIP 在 $\Delta P > 0$、$\Delta P = 0$、$\Delta P < 0$ 三组 skills 中的分布是否存在显著差异？

**RQ2（归因分析）：** 哪些 SIP 与 task outcome change 存在显著统计关联？建设性 SIPs 和破坏性 SIPs 的效应量分别是多少？

**RQ3（预测能力）：** 能否从 skill 文档和 project 的静态特征预测 skill injection 的效用？预测模型在 leave-one-skill-out 设置下的性能如何？

**RQ4（设计指导）：** 基于 RQ1-RQ3 的结果，能否提出可操作的 skill 设计原则？哪些 skill 特征（抽象级别、覆盖范围、版本处理方式）与正面效用正相关？

### 3.2 Agent 配置

| 参数 | 设置 | 理由 |
|------|------|------|
| Agent | Claude Code | SWE-Skills-Bench 的原始 agent；原生支持 skill discovery |
| Base model | Claude Sonnet 4 | 升级 SWE-Skills-Bench 的 Haiku 4.5，减少 ceiling effects（24 个 skill 在 Haiku 上已达 100% pass rate） |
| Temperature | 0（主分析）；0.7（variance estimation） | Temperature=0 确保 trace 差异可归因于 skill；0.7 估计随机方差 |
| Max turns | 与 SWE-Skills-Bench 一致 | 可比性 |
| Repetitions | 3 per condition | 估计跨 run 方差 |

### 3.3 Baselines

| Baseline | 描述 |
|----------|------|
| **Majority baseline** | 预测所有 skills 为 neutral（$\Delta P = 0$）。因为 80% 的 skills 确实是 neutral，这是一个强 baseline。 |
| **Skill length** | 仅用 skill 文档长度预测。测试"越长的 skill 越可能有害"的简单假设。 |
| **Semantic similarity** | 仅用 skill-project 语义相似度预测。测试"越相关的 skill 越有用"的直觉。 |
| **SUVA-adapted** | 将 SUVA 的 deductive coding 方法应用于 agent 的 reasoning text：定义一个 SWE 价值 codebook（correctness、efficiency、maintainability、compatibility），编码 reasoning 文本中的 value 出现，建模 value → outcome。这验证 CTA 的 trace-level structural analysis 是否提供了超越 text-level analysis 的信息。 |
| **Direct LLM-judge (no trace)** | 仅给 GPT-5 看 skill 文档 + project README，让它直接预测 utility 类别。验证 CTA pipeline 相对于"直接让 LLM 预测"是否提供了增量价值。 |

### 3.4 深度案例分析

除了统计分析，我们对以下 cases 进行详细的定性分析：

**Case 1: Best positive skill — `risk-metrics-calculation` ($\Delta P = +30\%$, $\rho = -34.8\%$)**
同时提升性能并降低 token 消耗的理想案例。分析 skill 如何通过 Procedural Scaffolding 提供 agent 参数化知识中不包含的金融公式。

**Case 2: Worst negative skill — `springboot-tdd` ($\Delta P = -10\%$, $\rho = -36.8\%$)**
Skill 降低性能且降低 token 消耗（agent 因 skill 干扰而更快地做出了错误决策）。分析 Surface Anchoring 如何导致 agent 复制不兼容的 Spring Boot 版本模板。

**Case 3: Maximum token overhead — `service-mesh-observability` ($\Delta P = 0\%$, $\rho = +450.8\%$)**
Skill 未改变结果但导致 token 消耗增加 4.5 倍。分析 Parallel Exploration 如何诱导 agent 探索大量 skill 中提到的替代方案后回到原始解。

**Case 4: `linkerd-patterns` ($\Delta P = -9.1\%$)**
SWE-Skills-Bench 中已详细分析的 context interference 案例（Figure 5）。通过 CTA 的 trace alignment 重新分析，展示如何通过 SIP detection 自动识别 surface anchoring → hallucination → concept bleed 的级联失败模式。

---

## 第五部分：预期产出与影响

### 5.1 学术产出

1. **一篇顶会论文**（NeurIPS 2026 Datasets & Benchmarks 或 ICLR 2027），标题暂定："Auditing Agent Skills: Counterfactual Trace Analysis Reveals When, How, and Why Skill Injection Alters Software Engineering Agent Behavior"

2. **一个公开数据集**：约 3,390 条结构化执行 traces（paired with/without skill），附带 SIP 标注和 divergence records。这是首个 agent skill trace-level 审计数据集。

3. **一个开源工具**：CTA pipeline（trace parser、phase segmenter、trace aligner、SIP classifier、skill quality predictor），可集成到 CI/CD 中作为 skill quality gate。


### 5.2 论文叙事线

论文的核心叙事：

1. **问题**：Agent skills 被大规模采用（136 天 84K+），但 80% 无效且部分有害（SWE-Skills-Bench 的发现）。当前评估是黑盒的，无法解释 why。

2. **Gap**：SUVA 展示了审计 LLM 推理过程的价值，但其 text-level CoT 分解不适用于 coding agent 的结构化执行 traces。缺少一个利用 paired condition 进行 counterfactual trace analysis 的框架。

3. **Method**：CTA 框架——trace parsing → phase segmentation → counterfactual alignment → SIP detection → divergence-outcome modeling → predictive assessment。

4. **Findings**：
   - 建设性 SIPs（PS, EP）集中在 7 个有效 skills 中，且主要出现在 domain-specific 的 procedural knowledge 场景
   - 破坏性 SIPs（SA, CB）在 3 个有害 skills 中占主导，且与 skill template specificity 高度相关
   - 中性 SIP (RE) 解释了 token overhead 与 performance 解耦的现象
   - Predictive model 可以从静态特征识别有害 skills

5. **Implications**：Skill 设计应偏向抽象指导模式（abstract guidance patterns），避免硬编码版本和参数的具体模板。Skill 部署前应通过 CTA predictor 进行质量评估。

---

## 第六部分：风险评估与缓解

| 风险 | 可能性 | 影响 | 缓解策略 |
|------|--------|------|---------|
| API 成本超预算 | 中 | 高 | Pilot 阶段严格估算；必要时减少 repetitions 到 1 次 |
| LLM judge 之间的 inter-rater agreement (Fleiss' κ) 不达标 (<0.6) | 中 | 中 | 迭代 prompt（增加 few-shot 示例、明确 SIP 边界定义）；如仍不达标，简化 SIP 分类体系为粗粒度三类 (constructive/neutral/destructive) 作为 fallback |
| LLM 标注与作者 gold set 一致性低 (<0.7) | 中 | 高 | 修订 prompt + 重新标注；最坏情况下采用 Path B (LLM-as-classifier at inference time) 绕过蒸馏环节 |
| LLM 标注引入系统性偏差（如对 own-model output 评价偏高） | 中 | 中 | 跨厂商 judge 设计 (GPT-5 + Claude) 已部分缓解；在 paper 的 limitations 章节明确讨论；gold set 上报告 LLM-vs-author disagreement 模式 |
| Sonnet 4 的 baseline pass rate 接近 100%（ceiling effect） | 中 | 高 | 如果 pilot 显示 ceiling effect，降级到 Haiku 4.5（与 SWE-Skills-Bench 一致） |
| Trace alignment 质量不足 | 中 | 中 | 退化为 phase-level only 分析（不做 intent-level alignment） |
| Predictive model 不 beat majority baseline | 中 | 中 | Reframe 为 ranking/anomaly detection（识别有害 skills）而非三分类 |
| SWE-Skills-Bench 作者发表扩展版本 | 中 | 低 | 我们的贡献是 trace-level 审计，与他们的 benchmark 扩展是正交的 |
| Reviewer 质疑仅使用 Claude Code 的泛化性 | 高 | 中 | Discussion 中讨论 multi-agent generalization；留作 future work |