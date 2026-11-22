---
name: fp-datahelper
description: 帮用户查看和处理 GC-MS、色谱或香气分析的 Excel 峰表，即使用户只上传文件或描述想得到的结果。可对齐不同样品的峰、算保留指数（RI）、查 CAS 号、嗅觉阈值或香气属性，以及标记含硅化合物。
---

# FP-DataHelper

## 先确认用户想得到什么

- 目标清楚时，直接用对应方法。列和分组能够从表里确认时，由 Agent 自行填写参数。只有缺少会影响结果的信息时才追问，尽量把必要问题合在一条消息里。
- 用户只给出文件、说「帮我整理一下」或问能做什么时，先只读查看工作表名和前 20 行的表头。根据实际看到的列，用通俗说法推荐一到两个操作，再问用户想要哪种结果。比如看到多组保留时间和名称列时，可以建议「把不同样品里的同名峰排到同一行」；看到 CAS 列时，可以建议「查这些化合物在水中的嗅觉阈值」。
- 对齐需要保留时间容差，单位为分钟。缺少容差时向用户确认；也可提供项目推荐预设的 `0.5` 分钟作为可选值。计算 RI 需要用户的正构烷烃参考表，缺少时说明需要碳数与保留时间两列。用户只说「查阈值」时可用完整库的默认最新值，并在交付时注明取值口径。
- CAS、香气属性和 NIST 对比会访问第三方站点，在用户请求相应查询时运行。

## 找到程序

- 从已安装的 Skill 目录读取可选的 `app-path.txt`，确认其中指向的项目目录包含 `fp_datahelper_cli.py` 和 `Methods/`。
- 从仓库直接读取本文件时，`skills/fp-datahelper/` 上两级就是项目根目录。也可以用用户提供的 FP-DataHelper 路径，或在工作区定位包含上述文件的项目副本。
- 从已安装的 Skill 目录读取 `python-path.txt` 选择解释器。也可使用已装 `Requirement.txt` 依赖的 Python 3.10 或更新版本。Windows 完整包的 `python-3.10.11-embed-amd64/python.exe` 可直接使用。Windows 没有可用 Python 时，按项目根目录的 `INSTALL-SKILL.md` 运行 `scripts/install_skill.ps1`。路径含空格时用当前 shell 的引号规则，PowerShell 调用带引号的可执行路径时使用 `&`。

## 检查更新

开始实际处理文件时，用同一解释器自行运行 `fp_datahelper_cli.py check-update`。已注册的 Skill 可加 `--skill-dir` 指定含当前 `SKILL.md` 的目录。每次工作流检查一次即可，程序会复用 24 小时内的检查结果，并尊重程序设置中的自动检查开关。

- `status` 为 `update_available` 时，交付文件时顺便告诉用户新版号和 `release_url`。
- `skill_refresh_available` 为 `true` 时，项目里的 Skill 内容和当前安装有差异。提示用户可从本项目使用安装脚本同步到原技能目录。
- 遇到离线、网络异常或关闭检查时继续处理文件。用户明确要求立即检查时可加 `--force`。下载和安装新版由用户决定。

## 运行任务

用当前 Agent 的终端调用 `fp_datahelper_cli.py`。在程序目录运行以下命令，或对脚本及工作簿使用绝对路径。用 `--help` 查看方法，用 `sort --help` 等查看对应方法参数。`--output-dir` 指向用户可访问的结果目录。命令按工作簿处理，用户指定个别工作表时先核对处理范围。

```text
python fp_datahelper_cli.py sort --input example.xlsx --rt-tolerance 0.5 --output-dir results
python fp_datahelper_cli.py ri --input 已生成的对齐文件.xlsx --alkanes exampleRI.xlsx --formula linear --output-dir results
```

按用户要求选择方法和参数。

| 命令 | 参数与处理行为 |
| --- | --- |
| `sort` | 按名称和保留时间对齐。`--rt-tolerance` 的单位为分钟，由用户指定。默认识别分组，必要时指定 `--group-width`。 |
| `ri` | `--alkanes` 指定正构烷烃参考表。默认线性插值及平均保留时间。可用 `--formula kovats` 或 `both`，以及 `--aggregate min` 或 `max`。指定 `--nist` 才联网比对。 |
| `threshold-simple` | 按 CAS 查询精简库预存的最小值。可用 `--cas-column` 指定列字母。 |
| `threshold-full` | 默认选最新阈值，有 CAS 时先按 CAS 查，查不到再按名称查。用 `--match cas` 或 `name`，配合 `--selection` 和 `--type-filter` 可指定筛选规则。 |
| `silicon` | 标红匹配含硅关键词的名称。可用 `--name-column` 指定列字母。 |
| `cas` | 按名称联网查询 NIST。遇到 `Ambiguous/List Found`，将歧义交给用户确认。 |
| `odor` | 按 CAS 查询 ChemicalBook，需要 Chrome 和网络。收到需要人工处理的错误时告诉用户失败原因。有可操作的终端和用户参与时，可加 `--interactive`，由用户处理浏览器并选择重试或输入 `n` 跳过。 |

从成功命令的标准输出 JSON 读取 `output_file`，确认生成了文件。串联时把这个路径作为下一步 `--input`。查看标准错误流中跳过的工作表、缺少公式计算值或查询未匹配的记录。失败时用一句话说明原因和用户需要补充的信息。交付时给出 Excel 文件，简述完成的处理，并指出会影响解读的遗漏或跳过项。
