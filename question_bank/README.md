# 面试题库（AI 侧）

本目录是「AI 模拟面试官」云端选题用的**离线题库**。当前共收录 **9615 道题、9 个岗位**：
原有中文与英文 AI 岗题库 2830 道，以及本次从同作者开源项目
[`xunzhekafei/myagent`](https://github.com/xunzhekafei/myagent)（MIT）迁移的 3 份题库 6785 道。
题库用于满足 [`../skills/README.md`](../skills/README.md) §5.1「面试问题库｜每岗位 50+ 题」
的数据需求。

**题只含题干，不含答案**（三个来源都如此，是有意保留的：模拟面试给候选人看到答案就失去意义了）。
云端只把题干当作**选题方向**注入提示词，不照读、不逐字念 —— 见
[`../cloud/question_bank.py`](../cloud/question_bank.py) 与 `../documents/progress_audit_2026-09-11.md` §11.21。

## 目录

```
question_bank/
├── README.md          ← 本文件（数据出处与许可说明）
├── LICENSE            ← 本目录文档/导入脚本许可，见下
├── data/
│   ├── zh_questions.json       1183 道中文 AI 岗题
│   ├── ai_questions.json       1647 道英文 AI 岗题
│   ├── fe_questions.json      6160 道前端工程师题（1,750,341 B）
│   ├── backend_questions.json  492 道后端开发工程师题（166,020 B）
│   └── algorithm_questions.json 133 道算法工程师题（41,065 B）
└── import/            ← 原有导入脚本，复现原有两份数据
    ├── import_dataset.py      从 HuggingFace 数据集导入英文题
    └── import_github_bank.py  从 8 个 GitHub 仓库导入中文题
```

## 数据文件与出处

数据文件的 SHA256：

| 文件 | 条数 | 大小 | sha256 |
| ---- | ----: | ----: | ------ |
| `zh_questions.json` | 1183 | 341,777 B（原记录） | `32aa229889f0fdef5a5f9639d5f41aa15b5a8c57c0972cedd8c1eeb4a20d5482` |
| `ai_questions.json` | 1647 | 1,440,845 B（原记录） | `2fbc293920ac019a19d6061ca450b3b53ff623d1d062712e64dc9d358920abb1` |
| `fe_questions.json` | 6160 | 1,750,341 B | `04615f646395109c1dfab1d288db11c38e70ac31a3c264e3011e6ed858fde3ff` |
| `backend_questions.json` | 492 | 166,020 B | `79cc8b5123ba7f665309936b76e7a385d5f71360059ea1ac88ebe3f05f734822` |
| `algorithm_questions.json` | 133 | 41,065 B | `07070bd64e42c41535a2ee9e67b634c70088b68953ec4db63902aa2c45b47012` |

> 注：前三个新增文件的 SHA256 按本次迁移后本地文件的 `Get-FileHash -Algorithm SHA256` 结果记录。
> 原有两份文件的大小和 SHA256 沿用迁移前 README 记录；本次尚未重新核对这两份文件的本地字节数。

### 本次迁移新增的 3 份题库 — 6785 道

数据源：[`xunzhekafei/myagent/interview/data`](https://github.com/xunzhekafei/myagent/tree/main/interview/data)，
上游项目许可为 **MIT**。

| 文件 | 条数 | 岗位 | 大小 | 许可 |
| ---- | ----: | ---- | ----: | ---- |
| `fe_questions.json` | 6160 | 前端工程师 | 1,750,341 B | MIT |
| `backend_questions.json` | 492 | 后端开发工程师 | 166,020 B | MIT |
| `algorithm_questions.json` | 133 | 算法工程师 | 41,065 B | MIT |
| **合计** | **6785** | **3 个岗位** | — | **MIT** |

本次迁移按原数据记录接入：**不改写 `question` 题干，保留 `source` 字段**。
三个文件均已按 `question/keywords/role/category/level/stage/lang/source` 字段进行校验；
记录数量分别为 6160、492、133，必需字段缺失数、空 `source` 数和空 `question` 数均为 0。

### `zh_questions.json` — 1183 道，全部中文

每条记录自带 `source` 字段（原样保留，可逐条核对），下表是汇总：

| 来源仓库 | 条数 | 岗位 | 许可 |
| ---- | ---- | ---- | ---- |
| [`guocong-bincai/ai-interview-guide`](https://github.com/guocong-bincai/ai-interview-guide) | 640 | AI 应用开发 | MIT |
| [`lengyue1024/BAT_interviews`](https://github.com/lengyue1024/BAT_interviews) | 208 | 大模型算法工程师 / AI 应用开发 | MIT |
| [`bcefghj/ai-agent-interview-guide`](https://github.com/bcefghj/ai-agent-interview-guide) | 181 | 智能体开发 | MIT |
| [`bcefghj/learn-nanobot`](https://github.com/bcefghj/learn-nanobot) | 134 | 智能体开发 | MIT |
| [`aceliuchanghong/FAQ_Of_LLM_Interview`](https://github.com/aceliuchanghong/FAQ_Of_LLM_Interview) | 20 | 大模型算法工程师 | MIT |

岗位分布：**AI 应用开发 748 / 智能体开发 315 / 大模型算法工程师 120**。
抽取时只取题目、不复制答案；各来源的目录白名单与排除规则（求职向目录、个人面经、
简历模板等）写在 `import/import_github_bank.py` 的 `SOURCES` 里，逐条可查。

### `ai_questions.json` — 1647 道，全部英文

| 来源 | 条数 | 岗位 | 许可 |
| ---- | ---- | ---- | ---- |
| [HuggingFace `Davichick/InterviewForge_GenDS`](https://huggingface.co/datasets/Davichick/InterviewForge_GenDS)（`interview_forge_v3_complete.csv`） | 1647 | 机器学习工程师 576 / 数据科学家 495 / 数据分析师 576 | MIT |

> ⚠️ **这份数据集没有 per-record 的来源字段**，上表因此是本仓能提供的**唯一**出处凭证 ——
> 删掉它就无法回溯这 1647 道题的来源了。原始 CSV 的拉取命令见 `import/import_dataset.py`。

## 字段说明

| 字段 | 类型 | 说明 |
| ---- | ---- | ---- |
| `question` | str | 题干（**唯一必填**，其余字段都可能为空） |
| `keywords` | list[str] | 检索关键词。原有英文题库 1647/1647 有值、原有中文题库 1183 条全为空数组；本次迁移三份数据保留上游字段和值 |
| `role` | str | 岗位。取值见上两节；**中文题库的岗位名带空格**（`AI 应用开发`） |
| `category` | str | 考点分类（如 `RAG 系统面试题`、`System Design & Architecture`），子串匹配 |
| `level` | str | 难度。原有英文题库有 `Level 1/2/3`，原有中文题库全为空；本次迁移三份数据保留上游字段和值 |
| `stage` | str | 面试阶段。原有英文题库四档全覆盖，原有中文题库仅 10 条有值（行为面）；本次迁移三份数据保留上游字段和值 |
| `lang` | str | 语言标记。原有中文题库与本次迁移的三份题库有该字段；具体值按原始记录保留 |
| `source` | str | 来源仓库。原有中文题库与本次迁移的三份题库有该字段；英文题库没有 |
| `url` | str | 原始 issue 链接。本仓五份数据里都没有该字段 |

## 许可

- 本目录的**导入脚本与文档**：MIT，见 [`LICENSE`](LICENSE)。
- **原有两份题库数据**：MIT。中文各源的 `source` 字段与上表逐条对应；英文来源为上述
  HuggingFace 数据集（MIT）。
- **本次新增三份题库数据**：来源为 [`xunzhekafei/myagent`](https://github.com/xunzhekafei/myagent)
  的 `interview/data/`，上游项目许可为 MIT。使用/再分发时请保留本文件的出处说明。

## 复现导入

两个脚本都在**仓库根目录**下运行，产物写回 `question_bank/data/`：

```bash
# 英文题（先拉原始 CSV，huggingface.co 直连不通时用 hf-mirror 镜像）
curl -L -o /tmp/interview_forge.csv \
  https://hf-mirror.com/datasets/Davichick/InterviewForge_GenDS/resolve/main/interview_forge_v3_complete.csv
python3 question_bank/import/import_dataset.py /tmp/interview_forge.csv

# 中文题（浅克隆 8 个仓库到临时目录后导入；加 --fresh 忽略已有克隆）
python3 question_bank/import/import_github_bank.py
```

⚠️ 导入依赖 GitHub / HuggingFace 的网络连通性，且会**覆盖** `data/` 下的同名文件。
重新导入后建议核对 sha256 是否仍与上表一致（上游仓库更新会导致题目变化）。
**离线校验题库本身不需要网络** —— 见 `../cloud/test_question_bank.py`。

## 迁移与适配说明

本次迁移前，本仓仅收录 `zh_questions.json` 与 `ai_questions.json` 两份题库，共 2830 道。
本次从同作者 `myagent` 项目的 `interview/data/` 追加迁移三份题库，共 6785 道；
迁移后五份数据合计 **9615 道、9 个岗位**。

1. **目录布局**：新增的三个 JSON 文件复制到本仓 `question_bank/data/`，与原有两份数据统一存放。
2. **数据内容**：本次迁移不改写题干，不删除原有 2830 道题，并保留新增记录的 `source` 字段。
3. **加载方式**：`cloud/question_bank.py` 使用 `BANK_FILES` **白名单**显式加载五份数据，
   不依赖 `glob("*.json")` 自动扫描，避免目录中其他 JSON 文件被意外加载。
4. **岗位适配**：云端岗位别名增加「前端 → 前端工程师」「后端 → 后端开发工程师」
   「算法 → 算法工程师」；板端岗位列表扩展为 9 个岗位。

## 已知局限

- **英文题干极长**：1647/1647 条都超过 60 字（中位数 508 字，最长 1068 字，多为多部分场景题）。
  注入提示词时会截断到 60 字，**只能当选题方向用，绝不能照读** —— 云端提示词里显式要求
  英文资料先译成中文再改写提问。演示岗位（AI 应用开发）走的是中文题库，不受影响。
- **中文题库无 `keywords`、无 `level`**：检索只能拿题干打分，难度只能靠提问方式控制
  （追问「为什么」「边界在哪」就是加难）。
- **题干口语化程度不一**：`FAQ_Of_LLM_Interview` 是笔记型仓库，题目由文件名生成，
  形如「请讲讲「X」的关键点，并结合实际场景举例。」—— 这类题更适合当话题引入。
- **不含答案**：有意为之。
- **题库岗位名带空格**（`AI 应用开发`）：在 NSH 里用 `set ROLE ...` 传参会**被空格切碎**
  （值只剩 `AI`），导致静默退化成自由提问。板子侧默认值改在 Kconfig 里，不走 `set`；
  详见 `../README.md` §4.7。

## 当前岗位与题量

当前题库覆盖 9 个岗位、共 9615 道题：

| 岗位 | 题数 |
| ---- | ----: |
| AI 应用开发 | 748 |
| 智能体开发 | 315 |
| 大模型算法工程师 | 120 |
| 机器学习工程师 | 576 |
| 数据科学家 | 495 |
| 数据分析师 | 576 |
| 前端工程师 | 6160 |
| 后端开发工程师 | 492 |
| 算法工程师 | 133 |
| **合计** | **9615** |

本次工作属于**题库迁移与适配（数据源：myagent，MIT）**，新增题库不是本仓原创题库。
