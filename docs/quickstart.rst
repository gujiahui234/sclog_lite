快速开始
========

安装
----

``sclog_lite`` 要求 Python 3.13 或更高版本。

.. code-block:: console

   python -m pip install -e .

仅使用控制台和文件
--------------------

.. code-block:: python

   from sclog_lite import setup_logger, shutdown

   logger = setup_logger()
   logger.info("控制台和文件")
   shutdown()

默认日志文件位于当前工作目录的 ``logs/`` 中。

同时写入 MySQL
--------------

.. code-block:: python

   from sclog_lite import MySQLConfig, setup_logger, shutdown

   logger = setup_logger(
       mysql=MySQLConfig(
           host="127.0.0.1",
           port=3306,
           user="app",
           password="secret",
           database="app_logs",
       )
   )
   logger.bind(request_id="req-001").info("三个位置同时输出")
   shutdown(timeout=10.0)

也可以通过 ``SCLOG_MYSQL_*`` 环境变量提供连接信息：

.. code-block:: python

   from sclog_lite import setup_logger

   logger = setup_logger(mysql=True)

程序退出
--------

模块注册了 ``atexit`` 刷新逻辑。服务进程仍推荐显式调用 ``shutdown()``，这样可以确认
退出前所有已排队记录都已写入数据库或失败隔离文件。
