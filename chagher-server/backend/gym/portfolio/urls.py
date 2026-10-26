from django.urls import path

from . import views

# نامک می‌تواند فارسی باشد ⇒ <str:…> (مبدلِ slug فقط حروفِ لاتین را می‌پذیرد)
urlpatterns = [
    path('team/', views.team_list, name='team-list'),
    path('team/<str:slug>/', views.member_detail, name='team-detail'),
    path('team/<str:slug>/pdf/', views.member_pdf, name='team-pdf'),
    path('team/<str:slug>/portfolio/', views.portfolio_list, name='team-portfolio'),
    path('portfolio/', views.portfolio_list, name='portfolio-list'),
    path('portfolio/<str:slug>/', views.project_detail, name='portfolio-detail'),
]
