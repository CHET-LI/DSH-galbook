# 各引擎支持情况

galbook 不解包、不解密、不运行游戏。你需要先用自己的工具把**剧本文本**和**图片**拿出来（常用：GARbro、KrkrExtract、unrpa/unrpyc、各引擎社区工具），再交给 `python3 -m galbook build`。

图例：✅ 分支（选项、路线、条件、跨周目变量都能玩） · 📖 线性（只能从头读到尾，没有选项） · 🛠 欢迎贡献

| 引擎 | 典型文件 | 现状 | 怎么准备 |
|---|---|---|---|
| **QLIE** | `*.pack` → `*.s` | ✅ | GARbro 解开 `data*.pack`，`--src` 指向含 `.s` 的目录 |
| **吉里吉里 KAG** | `*.xp3` → `*.ks` | ✅ | GARbro / KrkrExtract 解开；加密的 xp3 要先找到对应的解密方法 |
| **TyranoScript** | `data/scenario/*.ks` | ✅ | 网页版/打包版里直接有 `.ks` |
| **Ren'Py** | `*.rpy` / `*.rpyc` / `*.rpa` | ✅ | `.rpa` 用 unrpa，`.rpyc` 用 unrpyc 反编译成 `.rpy` |
| **NScripter / ONScripter** | `0.txt…` / `nscript.dat` | ✅ | `nscript.dat` 是简单异或，导入器自己会解；`arc.nsa` 里的图要另外解 |
| **galscript** | `*.gal` | ✅ | 自带的手写格式，自己写故事或手工移植，见 IMPORTERS.md |
| AdvHD | `*.ws2` | 📖 🛠 | VNTextPatch 抽 JSON → `--engine textdump` |
| Artemis | `*.pfs` → `*.ast` | 📖 🛠 | 同上。`.ast` 是 Lua 表格式，选项 `select` 可见，但跳转目标在别的脚本里，原生导入器欢迎贡献 |
| BGI / Ethornell | `*.arc` | 📖 | VNTextPatch `--format=ethornell` |
| CatSystem2 | `*.cst` | 📖 | VNTextPatch |
| Majiro | `*.mjo` | 📖 | VNTextPatch（字节码，分支需要反汇编器） |
| RealLive | `SEEN.TXT` | 📖 🛠 | VNTextPatch `--format=reallive`；RLdev 的 kprl 能反编译出带跳转的源码，原生导入器欢迎贡献 |
| SiglusEngine | `Scene.pck` | 🛠 | 字节码 + 按作品加密，目前没有现成的稳定文本工具链 |
| Softpal、SystemNNN、YU-RIS、Silky's/AI6WIN、Musica、Propeller、Kirikiri `.scn`、CatSystem2、Cyberworks、KaGuYa、Mware、ShSystem、Whale、TmrHiroAdvSystem、ArcGameEngine | 各异 | 📖 | VNTextPatch 支持的都能走 textdump |

## 验证程度（如实写）

- ✅ 里的 QLIE 用一部真实商业作品（不随仓库发布）跑通过：100 个脚本、1 个真选项、跨周目解锁第三条线、3 个 agent 同时玩；KAG / Ren'Py / NScripter 用照原引擎语法自写的样本测（`tests/samples/`），还没拿真作品跑过。
- 📖 textdump 的 JSON 格式按 VNTextPatch 源码（`JsonScript.cs`）实现，测试用的是自写样本；还没拿真游戏的 VNTextPatch 导出验证过。欢迎反馈。

## 线性（textdump）是什么体验

VNTextPatch 这类工具只抽台词，选项文字会混在台词里，跳转关系没有。所以导出来的书是一条直线：agent 能读完全文、能存读档、能看收集里的已读进度，但不会遇到选项。`story.json` 里 `mode: "linear"`，警告里也会写明。

想让某个引擎变成 ✅：写一个导入器（插件即可），见 [IMPORTERS.md](IMPORTERS.md)。需要的东西通常是：台词、选项（文字 + 去哪）、跳转/调用、条件和变量、结局在哪。

## 导入器各自的已知限制

- **QLIE**：识别 `^select`、`^selectpre`/`select.s`/`route.s` 这种「选项 → 路线表」结构，`#X` 当跨周目变量。宏写法特别花的作品可能有未识别指令，`build` 会列出 Top20。
- **KAG / Tyrano**：`[link]…[endlink]`、`[button]`、`[glink]` 当选项；`[if]/[elsif]/[else]/[endif]`、`[jump]`、`[call]/[return]`；`[iscript]` 里的 JS 只认简单赋值。自定义宏（`[macro]`）目前不展开，宏里藏着的台词/跳转会漏，未识别的标签会计入 Top20。
- **Ren'Py**：`menu:`、`jump`、`call`、`if/elif/else`、`$ x = …`、`default`、`persistent.`；`init`/`python:`/`screen`/`transform` 等块整块跳过，里面的逻辑不执行。
- **NScripter**：`select`/`selgosub`/`csel`、`goto`/`gosub`/`return`、`if`/`notif`、`mov`/`add`/`sub`；`%200` 以后当跨周目变量。
- **所有导入器**：图片按文件名在 `--assets-dir` 里找（不分大小写、忽略扩展名），找不到的会列出来；音乐只记名字不播放。

`build` 失败时会指明是哪个文件哪一行、哪条指令指向了不存在的标签，不会猜。


## 加一个新引擎：先看它属于哪一级

| 级 | 形态 | 能得到什么 |
|---|---|---|
| **A** | 明文脚本（`.ks` `.s` `.txt` `.rpy`） | 台词 + 选项 + 跳转 + 条件，整套可玩 |
| **B** | 加密脚本，但有已知密钥/算法（多数 KiriKiri、NScripter 的异或） | 同 A，多一步解密 |
| **C** | 字节码 / 编译产物（`.mjo` `Scene.pck`） | 台词多半能出；分支要先反汇编，不然只能线性 |
| **D** | 只能文本抽取（VNTextPatch 那一路） | 只有台词，选项混在正文里，没有跳转 |

一个引擎算「支持」，交付四样：**认引擎的判据**（`detect`）、**导入器**（`build`）、**自带合成样本 + 断言**（`tests/samples/<引擎>/`，不碰商业素材）、**文档一行**（典型文件 / 现状 / 怎么准备）。

## 防「静默丢分支」的四道闸

这条路最容易出的不是崩溃，是**看起来能玩、其实分支全没了**（3days：58762 句台词、403 场、59 个原作选择点，生成出来 `choice 0`）。

1. **`build` 打结构**：打印全库 op 直方图（say / choice / jump / end / …），一眼能看出分支是不是 0。
2. **选择点对数**：导入器报「脚本里认出 N 个选择点」，生成出来只有 M 个 ⇒ 直接记为校验问题。
3. **`books()` 自带体检**：每本书暴露 `choices` / `jumps` / `problems` / `warnings`；标了多条路线却 0 个选择点的书会被点名。
4. **`--strict`**：有未识别指令或上述对不上就退出码非 0，方便塞进批处理，不会「跑完了但其实坏的」。

## 老引擎照这个顺序做（按能覆盖的作品数排，不按年份）

1. **RealLive**（Key / VisualArt's 一大票）——有 RLdev 的 kprl 可参考，上限高
2. **BGI / Ethornell**（Buriko）——作品量大，社区工具有
3. **Majiro**——数量多，台词好出、分支要反汇编
4. **CatSystem2**——同上
5. **Artemis**（Jewel）——`.ast` 是 Lua 表，选项可见，跳转在别的脚本
6. **AdvHD**（WillPlus）、**System4**（AliceSoft）、**YU-RIS**、**Silky's / AI6WIN**
7. **NekoPack**（Lass 等，图像侧为主）、**SiglusEngine**（按作品加密）

判断标准只有一条：**能不能拿到明文或可解的脚本**。拿得到就做 A/B 级；只能抽文本就先挂 D 级，别假装支持。
