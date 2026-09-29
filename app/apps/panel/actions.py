"""
Действия с заявками из панели — общая реализация в apps.cashback.desk
(та же, что у API сотрудника и админ-API).
"""
from apps.cashback.desk import (STAFF_REJECT_REASONS, adjust, adjust_preview, confirm,  # noqa: F401
                                decline_escalation, queue, reject, search_members, shift)
from apps.cashback.desk import approve_escalation as approve_escalated  # noqa: F401
