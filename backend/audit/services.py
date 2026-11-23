from .middleware import clear_overrides, client_ip, current_request, noted_overrides
from .models import AuditEvent


def record(actor, action: str, entity: str, entity_id, **details) -> AuditEvent:
    """Write one audit event. Use for every state change and every refusal."""
    request = current_request()
    overridden = noted_overrides()
    if overridden:
        details["override"] = list(overridden)
    event = AuditEvent.objects.create(
        actor=actor if getattr(actor, "pk", None) else None,
        actor_username=getattr(actor, "username", "") or "",
        action=action,
        entity=entity,
        entity_id=str(entity_id),
        details=details,
        ip_address=client_ip(request) if request is not None else "",
    )
    if request is None:
        clear_overrides()  # the middleware ends them with the request; here, nothing else will
    return event
