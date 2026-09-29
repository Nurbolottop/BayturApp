import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateStorage(FileSystemStorage):
    """Выгрузки с персональными данными: вне MEDIA_ROOT, отдаются только через view с проверкой прав."""

    def __init__(self):
        super().__init__(location=os.path.join(settings.BASE_DIR, 'private'), base_url=None)

    def url(self, name):
        raise RuntimeError('Приватные файлы отдаются только через view с проверкой прав')


def private_storage():
    return PrivateStorage()
