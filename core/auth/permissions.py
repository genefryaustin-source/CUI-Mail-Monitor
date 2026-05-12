from core.auth.roles import ROLE_HIERARCHY, APPROVAL_RULES


def has_permission(user_role: str, required_role: str) -> bool:
    return ROLE_HIERARCHY.get(user_role, 0) >= ROLE_HIERARCHY.get(required_role, 0)


def can_approve(user_role: str, action_type: str) -> bool:
    required_role = APPROVAL_RULES.get(action_type, "ADMIN")
    return has_permission(user_role, required_role)