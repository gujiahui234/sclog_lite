架构与可靠性
============

数据路径
--------

每次 Loguru 调用会独立分发到三个处理器：

.. code-block:: text

   logger.info()
       ├── 控制台处理器
       ├── 文件处理器
       └── MySQL Sink
              └── 有界 Queue
                     └── 后台批处理线程
                            └── PyMySQL 连接池
                                   └── MySQL executemany()

数据库连接和批量插入不会在应用日志调用线程中执行。控制台或文件处理器也不依赖 MySQL
Sink 的成功状态。

批处理
------

后台线程取得第一条记录后，最多等待 ``flush_interval``，直到收集
``batch_size`` 条记录。随后使用一次 ``executemany()`` 和一次事务提交写入整个批次。

失败隔离
--------

数据库批次写入失败后按指数退避重试。超过 ``max_retries`` 后，每条记录和失败原因写入
``dead_letter_path`` 指定的 JSONL 文件。默认的 ``overflow_policy="dead_letter"``
也会隔离队列满时的新记录。

如果隔离文件本身不可写，记录会计入 ``dropped``，内部错误只写到标准错误，且不会重新
进入 Loguru，因而不会造成递归日志。

.. code-block:: python

   from sclog_lite import get_writer_stats

   stats = get_writer_stats()
   if stats is not None and (stats.failed or stats.dropped):
       # 将指标接入已有监控系统
       print(stats)

多进程说明
----------

连接池和后台队列属于当前 Python 进程。多进程服务应在每个子进程启动后调用
``setup_logger()``，不要在父进程创建 MySQL 连接后再 fork。

安全性
------

表名经过严格标识符校验，日志值全部通过 PyMySQL 参数化查询写入。密码字段不会出现在
``MySQLConfig`` 的 ``repr`` 中。失败隔离文件可能包含业务日志和异常信息，应限制其
文件权限并纳入数据保留策略。
