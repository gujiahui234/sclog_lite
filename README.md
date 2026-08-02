# sclog_lite

`sclog_lite` 是一个基于 [Loguru](https://github.com/Delgan/loguru) 的现代 Python
日志包。配置一次后，同一条日志可以同时写入控制台、文件和 MySQL。数据库写入在后台线程中
批量执行，不依赖 Kafka、Redis 或其他外部消息队列；数据库不可用时，控制台和文件日志仍会
正常工作。

## 环境要求

- Python 3.12 或更高版本
- MySQL 5.7+/8.x
- `loguru`
- `pymysql`

## 安装

```bash
python -m pip install -e .
```

开发环境：

```bash
python -m pip install -e ".[test,docs,dev]"
```

也可以使用 Conda：

```bash
conda env create -f environment.yml
conda activate sclog-lite
```

## 一行配置三个输出位置

直接传入数据库配置：

```python
from sclog_lite import MySQLConfig, setup_logger

logger = setup_logger(mysql=MySQLConfig(
    host="127.0.0.1",
    port=3306,
    user="app",
    password="secret",
    database="app_logs",
))
logger.info("这条日志会同时进入控制台、文件和 MySQL")
```

如果数据库连接信息已经放入环境变量，配置只需要一行：

```python
from sclog_lite import setup_logger; logger = setup_logger(mysql=True)
```

然后可以继续使用 Loguru 的全部原生 API：

```python
logger.bind(order_id=20260730).info("订单创建成功")
logger.exception("捕获异常")
logger.add("logs/extra_{time}.log", rotation="10 MB", retention="7 days")
```

所需环境变量：

```text
SCLOG_MYSQL_HOST=127.0.0.1
SCLOG_MYSQL_PORT=3306
SCLOG_MYSQL_USER=app
SCLOG_MYSQL_PASSWORD=secret
SCLOG_MYSQL_DATABASE=app_logs
SCLOG_MYSQL_TABLE=sclog_entries
```

## 文件输出

默认目录为当前项目工作目录下的 `logs/`。目录不存在时会自动创建，默认文件名格式为
`default_yyyymmdd-HHMMSS.log`。也可以指定完整路径：

```python
logger = setup_logger(
    mysql=True,
    file_path="D:/service-logs/backend.log",
    file_options={"rotation": "50 MB", "retention": "14 days", "compression": "zip"},
)
```

`console_options`、`file_options` 和 `mysql_handler_options` 会直接传给
`loguru.logger.add()`，因此过滤器、格式、日志级别、轮转和保留策略等行为与 Loguru 一致。

## 异步批量写入与失败隔离

```python
from sclog_lite import BatchConfig, PoolConfig, setup_logger

logger = setup_logger(
    mysql=True,
    pool=PoolConfig(min_size=0, max_size=8, acquire_timeout=5.0),
    batch=BatchConfig(
        batch_size=100,
        flush_interval=1.0,
        queue_size=10_000,
        max_retries=3,
        dead_letter_path="logs/mysql_failed.jsonl",
    ),
)
```

- 日志调用只负责把结构化记录放入进程内有界队列。
- 后台线程按数量或时间间隔批量调用 `executemany()`。
- 连接来自内置的线程安全 `pymysql` 连接池。
- 单个批次失败会按指数退避重试；最终失败后写入 JSONL 隔离文件。
- 队列满、数据库故障或隔离文件故障都不会让控制台和文件日志失效。
- 程序正常退出时会自动尝试刷新；也可以显式调用 `shutdown()`。

```python
from sclog_lite import get_writer_stats, shutdown

print(get_writer_stats())
shutdown(timeout=10.0)
```

## MySQL 表

默认会自动创建 `sclog_entries` 表。账号没有建表权限时，可以先执行
[`schema.sql`](schema.sql)，然后设置 `MySQLConfig(create_table=False)`。

数据库时间统一保存为 UTC，字段 `extra_json` 保存 `logger.bind()` 传入的结构化上下文。

## 测试与文档

```bash
pytest
sphinx-build -W -b html docs/source docs/build/html
python -m build
```

MySQL 集成测试默认跳过。配置 `SCLOG_TEST_MYSQL=1` 和对应的 `SCLOG_MYSQL_*` 变量后运行：

```bash
pytest -m integration
```

完整用法见 [`docs/`](docs/)。
