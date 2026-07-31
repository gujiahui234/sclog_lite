配置参考
========

Loguru 处理器
-------------

``setup_logger()`` 默认删除 Loguru 现有处理器，然后添加控制台和文件处理器。传入 MySQL
配置时再添加数据库处理器。``console_options``、``file_options`` 和
``mysql_handler_options`` 会覆盖默认值并直接传递给 ``logger.add()``。

.. code-block:: python

   logger = setup_logger(
       mysql=True,
       level="DEBUG",
       file_path="logs/service.log",
       console_options={
           "format": "<green>{time}</green> | <level>{level}</level> | {message}",
           "colorize": True,
       },
       file_options={
           "rotation": "100 MB",
           "retention": "30 days",
           "compression": "zip",
           "serialize": True,
       },
       mysql_handler_options={
           "filter": lambda record: record["level"].no >= 20,
       },
   )

MySQL 环境变量
--------------

.. list-table::
   :header-rows: 1

   * - 变量
     - 必填
     - 默认值
   * - ``SCLOG_MYSQL_USER``
     - 是
     - 无
   * - ``SCLOG_MYSQL_DATABASE``
     - 是
     - 无
   * - ``SCLOG_MYSQL_PASSWORD``
     - 否
     - 空字符串
   * - ``SCLOG_MYSQL_HOST``
     - 否
     - ``127.0.0.1``
   * - ``SCLOG_MYSQL_PORT``
     - 否
     - ``3306``
   * - ``SCLOG_MYSQL_TABLE``
     - 否
     - ``sclog_entries``
   * - ``SCLOG_MYSQL_CHARSET``
     - 否
     - ``utf8mb4``
   * - ``SCLOG_MYSQL_CREATE_TABLE``
     - 否
     - ``true``
   * - ``SCLOG_MYSQL_UNIX_SOCKET``
     - 否
     - 无

连接池与批处理
--------------

.. code-block:: python

   from sclog_lite import BatchConfig, PoolConfig, setup_logger

   logger = setup_logger(
       mysql=True,
       pool=PoolConfig(
           min_size=1,
           max_size=10,
           acquire_timeout=5.0,
           recycle_seconds=1800.0,
       ),
       batch=BatchConfig(
           batch_size=200,
           flush_interval=0.5,
           queue_size=20_000,
           max_retries=3,
           retry_backoff=0.25,
           retry_backoff_max=5.0,
           overflow_policy="dead_letter",
           dead_letter_path="logs/mysql_failed.jsonl",
       ),
   )

``queue_size`` 必须不小于 ``batch_size``。``min_size`` 连接在后台写入线程中预热，
因此 MySQL 暂时不可用不会阻止应用完成日志初始化。

关闭自动建表
------------

生产数据库账号通常不具备 DDL 权限。可以先用项目根目录的 ``schema.sql`` 建表：

.. code-block:: python

   from sclog_lite import MySQLConfig, setup_logger

   logger = setup_logger(
       mysql=MySQLConfig(
           user="app",
           password="secret",
           database="app_logs",
           create_table=False,
       )
   )
