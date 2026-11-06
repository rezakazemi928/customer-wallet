import uuid

from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import BaseUserManager
from django.db import models


class CustomerManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, mobile, national_code, password=None, **extra_fields):
        if not mobile:
            raise ValueError('Mobile is required.')
        if not password:
            raise ValueError('Password is required.')
        if not national_code:
                    raise ValueError('national code is required.')
        if 'email' in extra_fields:
            extra_fields['email'] = self.normalize_email(extra_fields['email'])
        user = self.model(
            mobile=mobile,
            national_code=national_code
            **extra_fields,
        )
        user.set_password(password)
        user.save(using=self._db)
        return user


class Customer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=150, unique=True, blank=True, null=True)
    email = models.EmailField(blank=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    password = models.CharField(max_length=128)
    mobile = models.CharField(max_length=20, unique=True)
    national_code = models.CharField(max_length=20, unique=True)
    birthdate = models.DateField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CustomerManager()

    class Meta:
        db_table = 'customers'

    def set_password(self, raw_password):
        if not raw_password:
            raise ValueError('Password is required.')
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        return check_password(raw_password, self.password)

    def save(self, *args, **kwargs):
        self.username = self.username or None
        super().save(*args, **kwargs)

    def __str__(self):
        return self.mobile
