sclog_lite 文档
=================

``sclog_lite`` 扩展 Loguru，使一条日志可以同时进入控制台、文件和 MySQL。MySQL
写入采用进程内后台线程、批处理和 PyMySQL 连接池；它不需要 Kafka、Redis 或其他外部队列。

.. toctree::
   :maxdepth: 2
   :caption: 使用指南

   quickstart
   configuration
   architecture
   api

核心特性
--------

* 返回 Loguru 原生 logger，不改变常用日志 API。
* 自动创建默认 ``logs/default_yyyymmdd-HHMMSS.log``。
* MySQL 后台批量写入和有界队列。
* 指数退避重试及 JSONL 失败隔离。
* 直接基于 PyMySQL 的线程安全连接池。
* PEP 517/518、Src Layout 和完整类型标记。
