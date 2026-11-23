from django.http import JsonResponse

# The largest upload is 20 MB; this leaves room for the form around it.
MAX_REQUEST_BYTES = 25 * 1024 * 1024


class RequestSizeLimitMiddleware:
    """Refuse an oversized request before anything reads it into memory or onto disk."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        length = request.META.get("CONTENT_LENGTH") or "0"
        if length.isdigit() and int(length) > MAX_REQUEST_BYTES:
            return JsonResponse({"detail": "That is too large to send. The limit is 25 MB."}, status=413)
        return self.get_response(request)
