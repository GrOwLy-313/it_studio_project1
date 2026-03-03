from .models import Message, Notification

def unread_messages(request):
    if request.user.is_authenticated:
        msg_count = Message.objects.filter(receiver=request.user, is_read=False).count()
        notif_count = Notification.objects.filter(user=request.user, is_read=False).count()
        return {
            'unread_count': msg_count,
            'notif_count': notif_count
        }
    return {'unread_count': 0, 'notif_count': 0}