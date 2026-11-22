# FP-DataHelper Skill 安装指南

本指南供能访问本地文件并运行终端命令的 Agent 使用。目标是在当前 Agent 中安装 `fp-datahelper`，并处理一份样例 Excel 验证安装。

## 定位项目和技能目录

1. 优先使用本地的完整项目副本。确认根目录包含 `fp_datahelper_cli.py`、`Methods/`、`scripts/install_skill.py` 和 `skills/fp-datahelper/SKILL.md`。需要获取项目时，使用官方仓库中包含这些文件的版本。把项目放在之后仍能访问的位置。[FP-DataHelper 仓库](https://github.com/Funny1Potato/FP-DataHelper)
2. 按当前 Agent 的文档或配置确认它读取的技能目录。安装脚本会在目录下创建 `fp-datahelper`，并记录程序和解释器的绝对路径。也可直接读取项目里的 `skills/fp-datahelper/SKILL.md`，在当前会话按说明调用终端程序。

## 安装

已有安装了 `Requirement.txt` 依赖的 Python 3.10 或更新版本时，在项目根目录使用该解释器执行安装脚本。

```text
python scripts/install_skill.py --skills-dir "当前 Agent 的技能目录"
```

Windows x64 没有可用 Python 时，在项目根目录运行 PowerShell 安装命令。

```powershell
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\scripts\install_skill.ps1 -SkillsDir "当前 Agent 的技能目录"
```

该脚本会复用完整包内置或已准备好的运行时。首次需要下载时，它会校验官方 Windows 完整包（约 122 MiB），并将运行时放在项目的 `output/skill-runtime/`。已有相同的 ZIP 时可用 `-RuntimeZip "完整包路径"`。也可以解压完整包，直接用包内 `python-3.10.11-embed-amd64\python.exe` 运行当前项目的 `scripts/install_skill.py`。[运行时来源](https://github.com/Funny1Potato/FP-DataHelper/releases/tag/0.3.1)

macOS 或 Linux 使用可用的 Python 3.10 或更新版本。终端环境缺少 Python 时，先通过该系统的包管理器或已有的运行环境准备解释器。然后可在项目内运行 `python -m venv .venv`，用虚拟环境里的 Python 运行 `-m pip install -r Requirement.txt`，并用同一解释器执行安装脚本。

更新 Skill 时，对原技能目录重新执行安装命令。

## 验证并交付

读取安装目录中的 `fp-datahelper/python-path.txt`，用记录的解释器运行下面的命令。确认返回的 `output_file` 指向已生成的 Excel 工作簿。程序会生成独立的结果文件。

```text
python fp_datahelper_cli.py sort --input example.xlsx --rt-tolerance 0.5 --output-dir output/skill-check
```

告诉用户如何在当前工具中调用 `fp-datahelper`，并说明他们可以直接给出 Excel 文件和想得到的结果。
