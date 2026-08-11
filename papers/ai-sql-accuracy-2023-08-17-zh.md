# AI SQL 准确率：测试不同 LLM 与上下文策略以最大化 SQL 生成准确率
_2023-08-17_

## 摘要

构建一个能够回答业务用户自然语言问题的自主 AI 代理，这一愿景极具吸引力，但至今仍难以实现。许多人曾尝试让 ChatGPT 编写 SQL，但成效有限。失败的主要原因在于 LLM 对被查询的特定数据集缺乏了解。

在本文中，**我们证明了上下文就是一切，有了正确的上下文，我们可以将准确率从约 3% 提升到约 80%**。我们探讨了三种不同的上下文策略，并展示了一种明显胜出的方案——将表结构定义、文档说明、以及历史 SQL 查询与相关性搜索相结合。

我们还对比了多种 LLM——包括 Google Bison、GPT 3.5、GPT 4，以及对 Llama 2 的简要尝试。虽然 **GPT 4 在 SQL 生成方面摘得桂冠**，但 Google 的 Bison 在提供足够上下文的情况下表现大致相当。

最后，我们展示了如何利用本文演示的方法为你的数据库生成 SQL。

以下是我们的核心发现总结——

![](https://raw.githubusercontent.com/vanna-ai/vanna/main/papers/img/summary.png)

## 目录
* [为什么使用 AI 生成 SQL？](#为什么使用-ai-生成-sql)
* [搭建测试架构](#搭建测试架构)
* [设置测试变量](#设置测试变量)
    * [选择数据集](#选择数据集)
    * [选择问题](#选择问题)
    * [选择提示词](#选择提示词)
    * [选择 LLM（基础模型）](#选择-llm基础模型)
    * [选择上下文](#选择上下文)
* [使用 ChatGPT 生成 SQL](#使用-chatgpt-生成-sql)
* [仅使用表结构](#仅使用表结构)
* [使用 SQL 样例](#使用-sql-样例)
* [使用上下文相关的样例](#使用上下文相关的样例)
* [分析结果](#分析结果)
* [进一步提升准确率的下一步工作](#进一步提升准确率的下一步工作)
* [为你的数据集使用 AI 编写 SQL](#为你的数据集使用-ai-编写-sql)

## 为什么使用 AI 生成 SQL？

如今，许多组织已经采用了某种数据仓库或数据湖——这是一个存储了大量组织关键数据、可供分析查询的存储库。这片数据海洋蕴藏着丰富的洞察潜力，但企业中只有极少数人具备利用这些数据所需的两项技能——

1. 对**高级 SQL** 的扎实掌握，以及
2. 对**组织独特的数据结构与表结构**的全面了解

同时具备以上两项技能的人不仅少之又少，而且很可能并不是那些提出大多数问题的人。

**那么组织内部实际发生了什么？** 业务用户，如产品经理、销售经理和高管，会有一些将影响业务决策和战略的数据问题。他们首先会查看仪表盘，但大多数问题都是临时性和特定的，答案无法在仪表盘中找到，于是他们会去找数据分析师或工程师——那些具备上述技能组合的人。这些人通常很忙，需要一段时间才能处理请求，而一旦业务用户得到答案，他们又会有后续问题。

**这个过程对双方都很痛苦**——业务用户需要漫长的等待才能得到答案，分析师则被分散了主要项目的精力，最终导致许多潜在的洞察被埋没。

![](https://raw.githubusercontent.com/vanna-ai/vanna/main/papers/img/question-flow.png)

**生成式 AI 登场！** LLM 为业务用户提供了用自然语言查询数据库的可能性（由 LLM 完成 SQL 翻译），我们已从数十家公司那里了解到，这将对他们的数据团队乃至整个业务产生颠覆性影响。

**关键挑战在于为复杂且混乱的数据库生成准确的 SQL**。我们接触过的许多人曾尝试使用 ChatGPT 编写 SQL，但成效有限、痛苦重重。许多人已经放弃，回归到手动编写 SQL 的老方法。最好的情况下，ChatGPT 也只是分析师获取正确语法的一个偶尔有用的辅助工具。

**但有希望！** 过去几个月，我们一直沉浸在这个问题中，尝试了各种模型、技术和方法来提高 LLM 生成 SQL 的准确率。在本文中，我们展示了各种 LLM 的性能表现，以及如何通过向 LLM 提供上下文相关的正确 SQL 样例来实现**极高的准确率**。

## 搭建测试架构

首先，我们需要定义测试的架构。以下是五步流程的概要，附伪代码——

![](https://raw.githubusercontent.com/vanna-ai/vanna/main/papers/img/test-architecture.png)

1. **问题** - 我们从业务问题开始。
```python
   question = "how many clients are there in germany"
```
2. **提示词** - 我们创建发送给 LLM 的提示词。
```python
   prompt = f"""
   Write a SQL statement for the following question:
   {question}
   """
```
3. **生成 SQL** - 使用 API，我们将提示词发送给 LLM 并获取生成的 SQL。
```python
   sql = llm.api(api_key=api_key, prompt=prompt, parameters=parameters)
```
4. **运行 SQL** - 在数据库上执行 SQL。
```python
    df = db.conn.execute(sql)
```
5. **验证结果** - 最后，验证结果是否符合预期。
结果评估中存在一些灰色地带，因此我们进行了人工评估。你可以在[这里](https://github.com/vanna-ai/research/blob/main/data/sec_evaluation_data_tagged.csv)查看评估结果。

## 设置测试变量

现在我们已经搭建好了实验框架，接下来需要确定哪些变量会影响准确率，以及我们的测试集是什么。我们测试了两个变量（LLM 和使用的训练数据），并在 20 个问题上运行了测试。因此，本次实验总共进行了 3 个 LLM × 3 种上下文策略 × 20 个问题 = 180 次独立试验。

![](https://raw.githubusercontent.com/vanna-ai/vanna/main/papers/img/test-levers.png)

### 选择数据集

首先，我们需要**选择一个合适的数据集**来测试。我们有以下几条指导原则——

1. **代表性**。企业中的数据集通常很复杂，而这种复杂性在许多演示/示例数据集中并未体现。我们希望使用一个包含真实用例和真实数据的复杂数据库。
2. **可获取性**。我们还希望该数据集是公开可用的。
3. **可理解性**。数据集应对广泛受众具有一定程度的可理解性——过于小众或技术性的内容将难以解读。
4. **维护性**。我们更倾向于选择一个得到良好维护和更新的数据集，以反映真实数据库的情况。

我们找到的符合上述标准的数据集是 Cybersyn SEC filings 数据集，可在 Snowflake 市场上免费获取：

https://docs.cybersyn.com/our-data-products/economic-and-financial/sec-filings

### 选择问题

接下来，我们需要**选择问题**。以下是一些示例问题（完整列表见此[文件](https://github.com/vanna-ai/research/blob/main/data/questions_sec.csv)）——

1. 数据集中有多少家公司？
2. 'ALPHABET INC.' 的利润表中有哪些年度指标？
3. 特斯拉的季度"汽车销售"和"汽车租赁"收入是多少？
4. 目前有多少家 Chipotle 餐厅？

现在我们有了数据集和问题，需要确定测试变量。

### 选择提示词

对于**提示词**，在本次测试中，我们将保持提示词不变，后续会进行改变提示词的跟进测试。

### 选择 LLM（基础模型）

对于要测试的 **LLM**，我们将尝试以下模型——

1. [**Bison（Google）**](https://cloud.google.com/vertex-ai/docs/generative-ai/learn/models) - Bison 是通过 GCP API 可用的 [PaLM 2](https://blog.google/technology/ai/google-palm-2-ai-large-language-model/) 版本。
2. [**GPT 3.5 Turbo（OpenAI）**](https://platform.openai.com/docs/models/gpt-3-5) - 直到最近，GPT 3.5 仍是 OpenAI 的旗舰模型，尽管 GPT 4 已经可用，但由于延迟和成本优势，以及准确率差异不大（嗯——我们将对此进行验证），尤其是在基础任务上，GPT 3.5 仍被广泛使用。
3. [**GPT 4（OpenAI）**](https://platform.openai.com/docs/models/gpt-4) - 更先进但性能较慢的 OpenAI 模型。GPT 4 是多模态的，但我们在本次测试中不会使用该功能。
4. [**Llama 2（Meta）**](https://ai.meta.com/llama/) - 我们非常希望纳入一个开源模型——领先的就是 Meta 的 Llama 2。但我们在 [Replicate](https://replicate.com/replicate/llama-2-70b-chat) 上的设置在发布前很快就崩溃了，我们未能及时修复。在早期的运行中，当它正常工作时，我们发现其表现充其量只能算中等。

### 选择上下文

最后，我们将使用三种类型的**上下文**。上下文指的是我们发送给 LLM 的、帮助 LLM 了解我们特定数据集的信息。

1. **仅表结构**。我们将表结构（使用 DDL）放入上下文窗口中。
2. **静态样例**。我们将静态的 SQL 查询样例放入上下文窗口中。
3. **上下文相关的样例**。最后，我们将最相关的上下文（SQL / DDL / 文档）放入上下文窗口中，通过基于嵌入向量的向量搜索来找到它们。

## 使用 ChatGPT 生成 SQL

这一节对 ChatGPT 来说有点不公平，但它是一个很好的起点。让我们直接拿一个问题让 ChatGPT 生成 SQL——

**提示词**

```
编写 Snowflake SQL 来回答以下问题——

Alphabet 各业务板块的季度收入是多少？

只返回 SQL
```

**回复**

当然，以下是 SQL 查询：

```sql
SELECT
  EXTRACT(QUARTER FROM date_column) AS quarter,
  business_segment,
  SUM(revenue) AS quarterly_revenue
FROM
  revenue_table
WHERE
  company_name = 'Alphabet'
GROUP BY
  quarter,
  business_segment
ORDER BY
  quarter,
  business_segment;

-- 请将 date_column、business_segment、revenue、revenue_table 替换为你具体数据库中的实际标识符。
```

不出所料，当我们尝试运行这段 SQL 时，会碰到错误，因为它编造了表名，因为我们没有提供——

![](https://raw.githubusercontent.com/vanna-ai/vanna/main/papers/img/sql-error.png)

当然，我们这样对 LLM 是不公平的——尽管它们很神奇，但它们（不幸地？幸运地？）不可能知道我们数据库里有什么——至少目前还不行。所以让我们进入提供更多上下文的测试。

## 仅使用表结构

首先，我们将数据集的表结构放入上下文窗口中。这通常是我们在 ChatGPT 教程中看到人们所做的。

一个示例提示词可能如下所示（实际中我们使用了 information schema 因为 Snowflake 共享的工作方式，但这展示了核心原理）——

```
用户提出问题，你提供 SQL。你只回复 SQL 代码，不做任何解释。

只回复 SQL 代码。不要回答任何解释——只输出代码。

你可以使用以下 DDL 语句作为可用表的参考。

CREATE TABLE Table1...

CREATE TABLE Table2...

CREATE TABLE Table3...
```

结果，简而言之，非常糟糕。在 60 次尝试中（20 个问题 × 3 个模型），只有两个问题被正确回答（均由 GPT 4 完成），**准确率低得可怜的 3%**。以下是 GPT 4 设法答对的两个问题——

1. 按频率排序的前 10 个指标描述是什么？
2. 报告属性中有哪些不同的报表？

![](https://raw.githubusercontent.com/vanna-ai/vanna/main/papers/img/accuracy-using-schema-only.png)

显然，仅使用表结构，我们远未达到成为有用的 AI SQL 代理的标准，尽管它作为分析师辅助工具可能有些用处。

## 使用 SQL 样例

如果我们设身处地地站在一个首次接触这个数据集的人的角度，除了表定义之外，他们首先会查看样例查询，以了解如何正确地查询数据库。

这些查询可以提供表结构中没有的额外上下文——例如，应该使用哪些列、表之间如何连接，以及查询该特定数据集的其他细微之处。

Cybersyn 与 Snowflake 市场上的其他数据提供商一样，在其文档中提供了几个（本例中为 3 个）样例查询。让我们将这些包含在上下文窗口中。

通过仅提供这 3 个样例查询，我们看到生成的 SQL 的正确性有了显著提升。然而，这种准确率因底层 LLM 的不同而有很大差异。似乎 GPT-4 最能将样例查询泛化，从而生成最准确的 SQL。

![](https://raw.githubusercontent.com/vanna-ai/vanna/main/papers/img/accuracy-using-static-examples.png)

## 使用上下文相关的样例

企业数据仓库通常包含数百（甚至数千）张表，以及数量级更多的、覆盖了组织内所有用例的查询。鉴于现代 LLM 上下文窗口的大小有限，我们不能简单地将所有历史查询和表结构定义一股脑地塞进提示词中。

我们最后的上下文策略是一种更高级的 ML 方法——将历史查询和表结构的嵌入向量加载到向量数据库中，并仅选择与所提问题最相关的查询/表。以下是我们在做什么的示意图——注意绿色框中标注的上下文相关性搜索——

![](https://raw.githubusercontent.com/vanna-ai/vanna/main/papers/img/using-contextually-relevant-examples.png)

通过向 LLM 展示最相关的 SQL 查询样例，即使是能力较弱的 LLM 也能大幅提升性能。在这里，我们向 LLM 提供与问题最相关的 10 个 SQL 查询样例（从存储的 30 个样例中选取），准确率飙升。

![](https://raw.githubusercontent.com/vanna-ai/vanna/main/papers/img/accuracy-using-contextual-examples.png)

我们可以通过维护一个历史上可执行且正确回答用户实际问题的 SQL 语句库来进一步提升性能。

## 分析结果

很明显，最大的差异并不在于 LLM 的类型，而在于为 LLM 提供适当上下文的策略（即所使用的"训练数据"）。

![](https://raw.githubusercontent.com/vanna-ai/vanna/main/papers/img/summary-table.png)

从按上下文策略划分的 SQL 准确率来看，显然这才是决定性的因素。我们从仅使用表结构时的约 3% 准确率，提升到了智能使用上下文相关样例时的约 80% 准确率。

![](https://raw.githubusercontent.com/vanna-ai/vanna/main/papers/img/summary.png)

LLM 本身仍然存在一些有趣的趋势。虽然 Bison 在"仅表结构"和"静态样例"两种策略中都处于垫底位置，但在完整的"上下文相关"策略下，它一跃升至榜首。三种策略取平均，**GPT 4 摘得了 SQL 生成最佳 LLM 的桂冠**。

![](https://raw.githubusercontent.com/vanna-ai/vanna/main/papers/img/accuracy-by-llm.png)

## 进一步提升准确率的下一步工作

我们很快将发布本次分析的后续研究，以更深入地探讨准确的 SQL 生成。下一步工作包括——

1. **使用其他数据集**：我们希望在其他的、真实的企业数据集上尝试这一方法。当表数量达到 100 张会怎样？1000 张呢？
2. **增加更多训练数据**：虽然 30 条查询已经很不错，但当数量提升 10 倍、100 倍时会发生什么？
3. **尝试更多数据库**：本次测试在 Snowflake 数据库上运行，但我们也在 BigQuery、Postgres、Redshift 和 SQL Server 上实现了相同功能。
4. **实验更多基础模型**：我们即将能够使用 Llama 2，我们也希望尝试其他 LLM。

我们对以上方面有一些初步的案例证据，但我们将扩展和完善我们的测试，以涵盖更多这些项目。

## 为你的数据集使用 AI 编写 SQL

虽然 SEC 数据是一个不错的起点，但你一定想知道这对你的数据和你的组织是否也适用。我们正在构建一个 [Python 包](https://vanna.ai)，它可以为你的数据库生成 SQL，并具备额外功能，如生成 Plotly 图表代码、处理后续问题以及各种其他功能。

以下是其工作原理概述：
```python
import vanna as vn
```

1. **使用表结构进行训练**

```python
vn.train(ddl="CREATE TABLE ...")
```

2. **使用文档进行训练**

```python
vn.train(documentation="...")
```

3. **使用 SQL 样例进行训练**

```python
vn.train(sql="SELECT ...")
```

4. **生成 SQL**

开箱即用 Vanna 的最简单方式是使用 `vn.ask(question="What are the ...")`，它将返回 SQL、表格和图表，如这个[示例 notebook](https://vanna.ai/docs/getting-started.html) 中所示。`vn.ask` 是对 `vn.generate_sql`、`vn.run_sql`、`vn.generate_plotly_code`、`vn.get_plotly_figure` 和 `vn.generate_followup_questions` 的封装。它将使用优化后的上下文为你生成 SQL，Vanna 会替你调用 LLM。

或者，你可以使用 `vn.get_related_training_data(question="What are the ...")`，如这个 [notebook](https://github.com/vanna-ai/research/blob/main/notebooks/test-cybersyn-sec.ipynb) 所示，它将检索最相关的上下文，你可以用它来构建自己的提示词，发送给任何 LLM。

这个 [notebook](https://github.com/vanna-ai/research/blob/main/notebooks/train-cybersyn-sec-3.ipynb) 展示了如何使用"静态"上下文策略在 Cybersyn SEC 数据集上训练 Vanna 的示例。

## 关于术语的说明
* **基础模型**：指底层的 LLM
* **上下文模型（亦称 Vanna 模型）**：这是一个位于 LLM 之上的层，为 LLM 提供上下文
* **训练**：当我们提到"训练"时，通常指的是对上下文模型的训练。

## 联系我们
如有任何问题，请通过 [Slack](https://join.slack.com/t/vanna-ai/shared_invite/zt-1unu0ipog-iE33QCoimQiBDxf2o7h97w)、[Discord](https://discord.com/invite/qUZYKHremx) 联系我们，或[预约 1 对 1 通话](https://calendly.com/d/y7j-yqq-yz4/meet-with-both-vanna-co-founders)。