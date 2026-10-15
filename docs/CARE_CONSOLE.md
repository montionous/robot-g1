# 护理工作台模块说明

## 当前导入范围

本仓库已导入 `care_console/` 的 27 个非运行时文件：11 个运行 Python 文件、7 个 Python 测试、一个 Node 测试、6 个静态页面文件、`.gitignore` 和 `deploy/requirements.txt`。附件未包含 README、审计或部署说明、systemd/Nginx 配置，也未包含任何 `runtime/` 文件。

`care_console/runtime/` 被根 `.gitignore` 整体忽略，认证改密过程产生的 `care_console/.auth-*` 临时文件也被忽略。该目录用于控制台 SQLite、认证资料、日志和截图，不能作为源码导入。工作台认证文件也应由部署环境在仓库外提供。

## 与语音场景的连接

四个普通 `run_g1_demo.sh` 会 source `speech/companion_recording_env.sh`。该脚本先创建本轮会话目录和 `care-session.jsonl` 路径，再执行：

```text
python3 -m care_console.link \
  --console-url ${CARE_CONSOLE_URL:-http://127.0.0.1:8766} \
  --elderly-id $G1_ELDERLY_ID \
  --interaction-log $CARE_SESSION_LOG
```

`link.py` 接受尚未出现的 JSONL 文件，向控制台预先登记本轮来源。它只允许连接 `127.0.0.1` 或 `localhost` 的 HTTP 地址，拒绝代理、认证信息、额外路径和重定向。登记过程会读取控制台概览与来源，并写入控制台自己的 SQLite；它不会直接写共享老人数据库。

启动脚本使用 `set -e`，因此本机工作台未启动、共享数据不完整或登记失败时，普通 G1 场景会在进入语音入口前停止。社交展示的 `run_g1_showcase.sh` 没有 source 这段环境脚本。

## 数据与运行边界

`create_app()` 默认使用 `care_console/runtime/console.db` 作为控制台数据文件，并只读访问 `speech/data/elder_companion.db`。调用 `create_app()` 会创建或迁移控制台数据库；默认生命周期还会启动定时同步。本轮没有调用它、没有启动 Uvicorn，也没有创建数据库。

工作台读取共享库中的 `elderly_person` 和 `elder_need`。因此在受控环境中运行前，至少需要基础老人表和 `speech/init_elder_need_db.py` 建立的需求表；控制台并不替代照护场景其余会话、记忆和个人档案初始化。

启动入口 `care_console.__main__` 在模块顶层解析命令行并调用 Uvicorn，只能作为显式 `python -m care_console` 命令使用，不适合作为普通导入检查。运行时依赖固定在 `care_console/deploy/requirements.txt`：FastAPI、Uvicorn 和 Pydantic；该清单没有合并到语音服务依赖中。

## 验证状态

附件解压前已检查路径和链接类型；共 28 个归档成员、无绝对路径、父目录跳转或链接。导入后与临时解压目录逐文件一致。120 个 Python 文件通过 AST 解析，10 个 Shell 脚本通过 `bash -n`，工作台静态文件的本地资源引用和三个 JavaScript 文件语法均通过检查。除 `__main__` 外的 10 个运行模块在拦截 SQLite、子进程和 HTTP 调用的条件下导入成功；`link.py` 也在实际 I/O 前拒绝外部 URL。未发现真实凭据、电话号码或老人档案。

在 `/tmp` 中临时安装 pytest 后，选择执行 `test_auth.py`、`test_business_records.py`、`test_console.py`、`test_interaction.py` 和 `test_records.py`：84 项中 83 项通过，1 项失败。失败项 `test_recovered_source_clears_io_error_but_retains_rejection_count` 在删除后重建同一路径的 JSONL 时依赖 inode 被复用；本环境分配新 inode 后，源码按设计将文件视为新一代并重读仍保留的 `invalid` 首行，因此保留“记录被拒绝”错误。单独重跑结果相同，原测试和业务代码均未修改。Node 原有 UI 测试 14 项全部通过。

这些 Python 用例只使用临时 SQLite 和进程内 ASGI 测试客户端，没有启动 Uvicorn、访问真实数据库或发起业务网络请求。`test_link.py` 还会启动 loopback HTTP server、执行临时 fake Python/curl；`test_replays.py` 会启动 `python -m care_console --help` 子进程。本轮没有运行这两份测试。
