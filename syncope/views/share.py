import secrets
from django.http import JsonResponse
from django.shortcuts import redirect, get_object_or_404
from django.views.decorators.http import require_http_methods
from syncope.models import Share, ShareVisit, Resource, Poll, PollPerson, Event, Project


BASE58_ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'


def generate_share_id(length=10):
    """Generate a random base58 string of given length."""
    return ''.join(secrets.choice(BASE58_ALPHABET) for _ in range(length))


@require_http_methods(["POST"])
def create_share_link(request):
    """
    Create a share link for a resource, poll, event, or project.

    Expects JSON payload:
    {
        "type": "resource" | "poll" | "event" | "project",
        "id": <object_pk>
    }

    Returns:
    {
        "share_id": "<base58_id>",
        "success": true
    }
    """
    try:
        import json
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    obj_type = data.get("type")
    obj_id = data.get("id")

    if not obj_type or obj_id is None:
        return JsonResponse({"error": "Missing 'type' or 'id' in request"}, status=400)

    # Map type to model and field name
    type_map = {
        "resource": (Resource, "resource"),
        "poll": (Poll, "poll"),
        "poll_person": (PollPerson, "poll_person"),
        "event": (Event, "event"),
        "project": (Project, "project"),
    }

    if obj_type not in type_map:
        return JsonResponse({"error": f"Invalid type: {obj_type}"}, status=400)

    model_class, field_name = type_map[obj_type]

    # Fetch the object; 404 if not found
    obj = get_object_or_404(model_class, pk=obj_id)

    # Return existing share if one already exists for this object
    existing = Share.objects.filter(**{field_name: obj}).first()
    if existing:
        return JsonResponse({"share_id": existing.id, "success": True})

    # Generate unique share_id
    while True:
        share_id = generate_share_id()
        if not Share.objects.filter(pk=share_id).exists():
            break

    # Create the share
    share = Share.objects.create(
        id=share_id,
        created_by=request.user if request.user.is_authenticated else None,
        **{field_name: obj}
    )

    return JsonResponse({
        "share_id": share.id,
        "success": True
    })


def visit_share(request, share_id):
    """
    Public endpoint to visit a shared link.

    Fetches the share, creates a visit record, determines which object
    the share points to, and redirects to the internal URL.
    """
    # Fetch the share; 404 if not found
    share = get_object_or_404(Share, pk=share_id)

    # Record the visit
    ip = request.META.get('HTTP_X_FORWARDED_FOR')
    if ip:
        ip = ip.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    ShareVisit.objects.create(share=share, ip_address=ip)

    # Determine which object the share points to and build redirect URL
    # All models have a user field (Poll, Event, Project) or owner field (Resource)
    if share.resource_id:
        return redirect(share.resource.url)
    elif share.poll_id:
        username = share.poll.user.username
        return redirect('syncope:poll_detail', username=username, pk=share.poll_id)
    elif share.poll_person_id:
        username = share.poll_person.poll.user.username
        return redirect('syncope:poll_person_attendance', username=username, pk=share.poll_person.poll_id, person_pk=share.poll_person.pk)
    elif share.event_id:
        username = share.event.user.username
        return redirect('syncope:event_detail', username=username, pk=share.event_id)
    elif share.project_id:
        username = share.project.user.username
        return redirect('syncope:project_detail', username=username, pk=share.project_id)

    # This shouldn't happen due to the CheckConstraint, but fallback anyway
    return JsonResponse({"error": "Share has no associated object"}, status=500)
