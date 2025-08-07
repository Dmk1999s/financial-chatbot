import os

DB_USER: os.getenv('DB_USER')
# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#   * Rearrange models' order
#   * Make sure each model has one field with primary_key=True
#   * Make sure each ForeignKey and OneToOneField has `on_delete` set to the desired behavior
#   * Remove `managed = False` lines if you wish to allow Django to create, modify, and delete the table
# Feel free to rename the models, but don't rename db_table values or field names.
from django.db import models


class Annuity(models.Model):
    avg_prft_rate = models.FloatField(blank=True, null=True)
    btrm_prft_rate1 = models.FloatField(blank=True, null=True)
    guar_rate = models.FloatField(blank=True, null=True)
    id = models.BigAutoField(primary_key=True)
    fin_prdt_nm = models.CharField(max_length=255, blank=True, null=True)
    join_way = models.CharField(max_length=255, blank=True, null=True)
    kor_co_nm = models.CharField(max_length=255, blank=True, null=True)
    pnsn_kind_nm = models.CharField(max_length=255, blank=True, null=True)
    prdt_type_nm = models.CharField(max_length=255, blank=True, null=True)
    sale_co = models.TextField(blank=True, null=True)
    sale_strt_day = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'annuity'


class AuthUser(models.Model):
    password = models.CharField(max_length=128)
    last_login = models.DateTimeField(blank=True, null=True)
    is_superuser = models.IntegerField()
    username = models.CharField(unique=True, max_length=150)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    email = models.CharField(max_length=254)
    is_staff = models.IntegerField()
    is_active = models.IntegerField()
    date_joined = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'auth_user'


class Comment(models.Model):
    created_at = models.DateTimeField()
    deleted_at = models.DateTimeField(blank=True, null=True)
    id = models.BigAutoField(primary_key=True)
    parent = models.ForeignKey('self', models.DO_NOTHING, blank=True, null=True)
    post = models.ForeignKey('Post', models.DO_NOTHING, blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    user = models.ForeignKey('User', models.DO_NOTHING, blank=True, null=True)
    content = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'comment'


class Deposit(models.Model):
    id = models.BigAutoField(primary_key=True)
    etc_note = models.CharField(max_length=1000, blank=True, null=True)
    mtrt_int = models.CharField(max_length=1000, blank=True, null=True)
    spcl_cnd = models.CharField(max_length=1000, blank=True, null=True)
    fin_prdt_nm = models.CharField(max_length=255, blank=True, null=True)
    join_member = models.CharField(max_length=255, blank=True, null=True)
    join_way = models.CharField(max_length=255, blank=True, null=True)
    kor_co_nm = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'deposit'


class Post(models.Model):
    created_at = models.DateTimeField()
    deleted_at = models.DateTimeField(blank=True, null=True)
    id = models.BigAutoField(primary_key=True)
    like_num = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    user = models.ForeignKey('User', models.DO_NOTHING, blank=True, null=True)
    content = models.CharField(max_length=255, blank=True, null=True)
    title = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'post'


class PostLike(models.Model):
    id = models.BigAutoField(primary_key=True)
    post = models.ForeignKey(Post, models.DO_NOTHING, blank=True, null=True)
    user = models.ForeignKey('User', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'post_like'


class PostScrap(models.Model):
    id = models.BigAutoField(primary_key=True)
    post = models.ForeignKey(Post, models.DO_NOTHING, blank=True, null=True)
    user = models.ForeignKey('User', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'post_scrap'


class Savings(models.Model):
    id = models.BigAutoField(primary_key=True)
    etc_note = models.CharField(max_length=1000, blank=True, null=True)
    mtrt_int = models.CharField(max_length=1000, blank=True, null=True)
    spcl_cnd = models.CharField(max_length=1000, blank=True, null=True)
    fin_prdt_nm = models.CharField(max_length=255, blank=True, null=True)
    join_member = models.CharField(max_length=255, blank=True, null=True)
    join_way = models.CharField(max_length=255, blank=True, null=True)
    kor_co_nm = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'savings'


class User(models.Model):
    social_type = models.IntegerField(blank=True, null=True)
    age = models.BigIntegerField(blank=True, null=True)
    created_at = models.DateTimeField()
    deleted_at = models.DateTimeField(blank=True, null=True)
    expected_income = models.BigIntegerField(blank=True, null=True)
    expected_loss = models.BigIntegerField(blank=True, null=True)
    gender = models.BigIntegerField(blank=True, null=True)
    id = models.BigAutoField(primary_key=True)
    income = models.BigIntegerField(blank=True, null=True)
    period = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    email = models.CharField(max_length=255, blank=True, null=True)
    funding_situation = models.CharField(max_length=255, blank=True, null=True)
    income_source = models.CharField(max_length=255, blank=True, null=True)
    income_stability = models.CharField(max_length=255, blank=True, null=True)
    investment_proportion = models.CharField(max_length=255, blank=True, null=True)
    investment_type = models.CharField(max_length=255, blank=True, null=True)
    nickname = models.CharField(max_length=255, blank=True, null=True)
    password = models.CharField(max_length=255, blank=True, null=True)
    purpose = models.CharField(max_length=255, blank=True, null=True)
    role = models.CharField(max_length=255, blank=True, null=True)

    risk_tolerance = models.CharField(max_length=255, blank=True, null=True)
    asset_allocation_type = models.IntegerField(blank=True, null=True)
    value_growth = models.IntegerField(blank=True, null=True)
    risk_acceptance_level = models.IntegerField(blank=True, null=True)
    investment_concern = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        managed = True
        db_table = 'user'
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['nickname']),
            models.Index(fields=['created_at']),
            models.Index(fields=['updated_at']),
            # 금융상품 추천 기준 인덱스
            models.Index(fields=['risk_tolerance']),
            models.Index(fields=['asset_allocation_type']),
            models.Index(fields=['value_growth']),
            models.Index(fields=['risk_acceptance_level']),
            models.Index(fields=['investment_concern']),
            # 복합 인덱스 (주요 조합)
            models.Index(fields=['risk_tolerance', 'risk_acceptance_level']),
            models.Index(fields=['asset_allocation_type', 'value_growth']),
        ]
