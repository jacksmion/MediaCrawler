# -*- coding: utf-8 -*-
#
# Runtime database ORM models.

from sqlalchemy import BigInteger, Column, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class RuntimeNormalizedContent(Base):
    __tablename__ = "runtime_normalized_content"

    content_key = Column(String(255), primary_key=True, comment="平台内容唯一键")
    platform_code = Column(String(64), nullable=False, index=True, comment="平台编码")
    platform_content_id = Column(String(255), nullable=False, index=True, comment="平台内容ID")
    content_type = Column(String(64), nullable=False, comment="内容类型")
    title = Column(Text, comment="标题")
    body_text = Column(Text, comment="正文")
    url = Column(Text, comment="内容链接")
    author_platform_id = Column(String(255), comment="作者平台ID")
    published_at = Column(String(64), comment="发布时间")
    raw_payload = Column(Text, comment="原始负载")
    metadata_json = Column("metadata", Text, comment="元数据")
    add_ts = Column(BigInteger, comment="添加时间戳")
    last_modify_ts = Column(BigInteger, comment="最后修改时间戳")


class RuntimeRawRecord(Base):
    __tablename__ = "runtime_raw_record"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    snapshot_id = Column(String(64), nullable=False, unique=True, index=True, comment="快照ID")
    platform_code = Column(String(64), nullable=False, index=True, comment="平台编码")
    record_type = Column(String(64), nullable=False, index=True, comment="记录类型")
    source_uri = Column(Text, comment="来源地址")
    fetched_at = Column(String(64), comment="抓取时间")
    request_meta = Column(Text, comment="请求元数据")
    response_body = Column(Text, comment="响应体")
    content_hash = Column(String(255), comment="内容哈希")
    metadata_json = Column("metadata", Text, comment="元数据")
    add_ts = Column(BigInteger, comment="添加时间戳")


class RuntimeCrawlTaskSnapshot(Base):
    __tablename__ = "runtime_crawl_task_snapshot"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    snapshot_id = Column(String(64), nullable=False, unique=True, index=True, comment="快照ID")
    task_id = Column(String(255), nullable=False, index=True, comment="任务ID")
    platform_code = Column(String(64), nullable=False, index=True, comment="平台编码")
    task_type = Column(String(64), nullable=False, comment="任务类型")
    status = Column(String(64), nullable=False, comment="任务状态")
    schedule_type = Column(String(64), nullable=False, comment="调度类型")
    priority = Column(Integer, default=0, comment="优先级")
    params = Column(Text, comment="任务参数")
    created_at = Column(String(64), comment="创建时间")
    updated_at = Column(String(64), comment="更新时间")
    add_ts = Column(BigInteger, comment="添加时间戳")


class RuntimeCrawlJobSnapshot(Base):
    __tablename__ = "runtime_crawl_job_snapshot"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    snapshot_id = Column(String(64), nullable=False, unique=True, index=True, comment="快照ID")
    job_id = Column(String(255), nullable=False, index=True, comment="作业ID")
    task_id = Column(String(255), nullable=False, index=True, comment="任务ID")
    platform_code = Column(String(64), nullable=False, index=True, comment="平台编码")
    status = Column(String(64), nullable=False, comment="作业状态")
    batch_id = Column(String(255), comment="批次ID")
    started_at = Column(String(64), comment="开始时间")
    ended_at = Column(String(64), comment="结束时间")
    error_code = Column(String(255), comment="错误码")
    error_message = Column(Text, comment="错误信息")
    metrics = Column(Text, comment="统计信息")
    add_ts = Column(BigInteger, comment="添加时间戳")


class RuntimeCrawlResultSnapshot(Base):
    __tablename__ = "runtime_crawl_result_snapshot"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    snapshot_id = Column(String(64), nullable=False, unique=True, index=True, comment="快照ID")
    job_id = Column(String(255), nullable=False, index=True, comment="作业ID")
    platform_code = Column(String(64), nullable=False, index=True, comment="平台编码")
    task_kind = Column(String(64), nullable=False, comment="任务种类")
    success = Column(Integer, default=0, comment="是否成功")
    payload = Column(Text, comment="结果负载")
    metrics = Column(Text, comment="统计信息")
    error_code = Column(String(255), comment="错误码")
    error_message = Column(Text, comment="错误信息")
    created_at = Column(String(64), comment="结果创建时间")
    add_ts = Column(BigInteger, comment="添加时间戳")


class RuntimeCrawlEventSnapshot(Base):
    __tablename__ = "runtime_crawl_event_snapshot"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    snapshot_id = Column(String(64), nullable=False, unique=True, index=True, comment="快照ID")
    job_id = Column(String(255), nullable=False, index=True, comment="作业ID")
    platform_code = Column(String(64), nullable=False, index=True, comment="平台编码")
    event_type = Column(String(128), nullable=False, index=True, comment="事件类型")
    message = Column(Text, comment="事件消息")
    details = Column(Text, comment="事件详情")
    created_at = Column(String(64), comment="事件创建时间")
    add_ts = Column(BigInteger, comment="添加时间戳")
