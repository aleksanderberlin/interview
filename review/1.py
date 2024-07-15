from django.db.models import Prefetch, QuerySet
from notification.serializers import (
    NotificationCreateSerializer,
    NotificationMainSerializer
)
from rest_framework import status, serializers
from rest_framework.generics import (
    RetrieveAPIView,
    UpdateAPIView,
    get_object_or_404,
)
from celery import shared_task
from rest_framework.generics import CreateAPIView, DestroyAPIView, ListAPIView
from rest_framework.response import Response

from license.models import User
from notification.models import Notification
from .utils import update_related_objects, notify_admins


class CreateLicenseeNotificationView(CreateAPIView):
    queryset = Notification.objects.all()
    serializer_class = NotificationCreateSerializer

    def create(self, request, *args, **kwargs) -> Response:
        license_user_obj = get_object_or_404(
            User,
            pk=kwargs["licensee_pk"],
        )

        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save(
                subscriber=request.user,
                license_user=license_user_obj
            )
        else:
            raise serializers.ValidationError(serializer.errors)

        # Send email with Celery task
        from .tasks import send_email_celery
        send_email_celery.delay(license_user_obj)

        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )


class ListLicenseeNotificationView(ListAPIView):

    class NotificationSerializer(serializers.ModelSerializer):
        class Meta:
            model = Notification
            fields = ("id", "license_user", "days_expires")

    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer

    def get_queryset(self) -> QuerySet[Notification]:
        queryset = super().get_queryset()

        license_user_obj = get_object_or_404(
            User,
            pk=self.kwargs["licensee_pk"],
        )
        queryset.filter(
            license_user=license_user_obj, user=self.request.user
        )
        return queryset


class DetailNotificationView(RetrieveAPIView):
    """
    View for getting Notification by id.
    """

    queryset = Notification.objects.all()
    serializer_class = NotificationMainSerializer

    def get_queryset(self) -> QuerySet[Notification]:
        queryset = super().get_queryset()

        queryset.filter(
                    user=self.request.user
        )
        return queryset

    def get_object(self) -> Notification:
        object = super().get_object()
        object.counter += 1
        object.save()
        return object


@shared_task
def celery_notify_admins():
    res = notify_admins()
    return res


@shared_task
def celery_update_related_objects():
    """
    Celery task for sending notifications via email.
    """
    update_related_objects()
    celery_notify_admins.delay()


class UpdateNotificationView(UpdateAPIView):
    """
    View for Notification updating.
    """

    serializer_class = NotificationMainSerializer
    http_method_names = ("post",)

    def get_queryset(self) -> QuerySet[Notification]:
        queryset = Notification.objects.filter(user=self.request.user)
        return queryset

    def update(self, request, *args, **kwargs):
        celery_update_related_objects.delay()
        return super().update(request, *args, **kwargs)
