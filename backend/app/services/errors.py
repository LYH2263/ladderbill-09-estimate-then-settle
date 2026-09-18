class DomainError(Exception):
    """业务规则冲突（如双有效抄表）。消息面向用户可读，路由层映射为 HTTP 409。"""


class NotFoundError(Exception):
    """资源不存在，路由层映射为 HTTP 404。"""
