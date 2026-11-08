from django.urls import path

from core.accounts.views import LogoutView, SessionView
from core.accounts.wechat_views import (
    WechatBindingView,
    WechatLoginView,
    WechatLogoutView,
    WechatUnbindView,
)

urlpatterns = [
    path("api/v1/auth/wechat/login/", WechatLoginView.as_view()),
    path("api/v1/auth/wechat/binding/", WechatBindingView.as_view()),
    path("api/v1/auth/wechat/logout/", WechatLogoutView.as_view()),
    path("api/v1/auth/wechat/unbind/", WechatUnbindView.as_view()),
    path("api/v1/auth/session/", SessionView.as_view()),
    path("api/v1/auth/logout/", LogoutView.as_view()),
]
