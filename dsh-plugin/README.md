# DSH 插件包（给 DeepSeek Harness 用户）

**三步装好，不需要 API key。**

```bash
# 1. 解开这个包，进到目录
cd DSH-galbook

# 2. 装演示书（中文 + 英文两本，几十 KB）
python -m galbook demo --books books

# 3. 挂进 dsh（自动找 profile、自动备份、自动填路径）
python dsh-plugin/install.py
```

然后重启 DeepSeek Harness，新建会话问一句「galbook 有哪些工具？」，能看到 14 个就成了。

## 它会做什么

- 找到 `<dsh-home>/profiles/<profile>/cordis.patch.yml`（默认 profile `desktop`，`dsh-home` 默认 `~/.dsh`，可用 `DSH_HOME` 或 `--home` 指定）
- 先备份成 `cordis.patch.yml.bak-时间戳`
- 在文件末尾追加一段 `mcp-galbook`（stdio 方式，dsh 自己拉起 `python -m galbook mcp`），里面的路径按你这台机器填好
- 不动 dsh 本体，不动别的配置条目；重复执行不会写两遍

```bash
python dsh-plugin/install.py --dry-run          # 只看要写什么
python dsh-plugin/install.py --profile work     # 装到别的 profile
python dsh-plugin/install.py --books D:/books --data D:/saves
python dsh-plugin/install.py --remove           # 卸载
```

## 另外两种接法

- **共享服务**：`python -m galbook serve --books books --port 8765`，多个 agent 共用一个进程，令牌绑定名字，URL 里冒名无效。配置见 `integrations/deepseek-harness/galbook-http.patch.yml`。
- **命令行**：`python -m galbook do next n=20`，给只有 shell 的 agent 用，最后一行就是下一步该跑的命令。

## 技能文件

`.agents/skills/galbook/SKILL.md` 已经在包里。从仓库根启动 dsh 时会自动发现，里面写明了「不准偷看剧本文件」——agent 只能通过工具一步步读剧情。

## 出问题怎么办

- **Linux 上解压后目录名变乱码**（`уВ╣уВпуГкуГЧуГИ` 这种）：系统的 `unzip` 不认 UTF-8 文件名。用 `python3 -m zipfile -e galbook-1.2.0.zip .`，或直接下 `galbook-1.2.0.tar.gz`
- **连 GitHub 超时 / 提示「请尝试其他安装来源」**：这台机器到 github.com 不通时，插件面板的链接安装会失败。两个办法：
  - 用本地安装：把仓库解压到本地，插件面板里选**本地目录**；或下载 `dsh-galbook-1.2.0.tgz`（Release 里），来源填 `file:C:\路径\dsh-galbook-1.2.0.tgz`
  - 给 dsh 走代理：启动 dsh 前设 `HTTPS_PROXY` / `HTTP_PROXY`（例如 `http://127.0.0.1:7897`），再重试链接安装
- 看不到工具：确认改的是**当前在用的** profile；dsh 的配置只在启动时读，改完必须整组退出重开
- `python` 找不到：`python dsh-plugin/install.py --python "C:\Path\python.exe"`
- 想手动看写了什么：`--dry-run` 打印的就是最终 YAML
